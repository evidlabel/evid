"""Replace a document's PDF in place, keeping its uuid, labels and machine quotes.

did hands a case's documents over as placeholder PDFs (``[PERSON 1]``). When did's review
changes and the documents are handed over again, the identities may be numbered anew
(``[PERSON 1]`` is now ``[PERSON 4]``). Labels are verbatim spans, so a label whose text
holds an old placeholder no longer matches. ``replace`` therefore:

1. puts the new PDF in place (``original.pdf``) and takes its title when it has one;
2. rewrites the label map (old placeholder → new) inside every stored span — text and
   context — all at once, so swaps (1→4 and 4→1) do not chain;
3. extracts the text again and re-anchors every label, annotation and machine quote
   (same, moved, fuzzy) — what still cannot be found is marked ``lost`` (stale);
4. commits the document's ``label/`` and ``pass/`` in git.

``stale`` lists the lost records of a set; ``repair`` asks a model (any command that reads
a prompt on stdin and answers on stdout: ``$EVID_REPAIR_CMD``, default ``claude -p``) to
pick the passage a lost record now points at, from candidate passages of the new text. A
proposal is accepted only when it is found verbatim in the text: the quote is always the
document's own bytes, never the model's.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from rapidfuzz import fuzz

from evid.core import gitops, labels, quote_pass
from evid.core.spans import make_span

ORIGINAL = "original.pdf"


def _apply_map(s: str, rx: re.Pattern | None, mapping: dict) -> str:
    return rx.sub(lambda m: mapping[m.group(0)], s) if rx and s else s


def _map_record(rec: dict, rx, mapping) -> dict:
    out = dict(rec)
    for k in ("text", "prefix", "suffix"):
        if isinstance(out.get(k), str):
            out[k] = _apply_map(out[k], rx, mapping)
    return out


def replace(doc_dir: Path, new_pdf: Path, label_map: dict | None = None) -> dict:
    """Swap the document's PDF for NEW_PDF and carry every label across. Returns counts."""
    doc_dir, new_pdf = Path(doc_dir), Path(new_pdf)
    if not (doc_dir / "info.yml").is_file():
        raise FileNotFoundError(f"no document at {doc_dir}")
    if not new_pdf.is_file():
        raise FileNotFoundError(f"no file {new_pdf}")
    mapping = {str(k): str(v) for k, v in (label_map or {}).items() if k and k != v}
    rx = (
        re.compile(
            "|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True))
        )
        if mapping
        else None
    )

    tmp = doc_dir / (ORIGINAL + ".new")
    shutil.copyfile(new_pdf, tmp)
    tmp.replace(doc_dir / ORIGINAL)
    title = _pdf_title(doc_dir / ORIGINAL)
    if title:
        _set_info(doc_dir, title=title, label=title)

    if labels.has_text(doc_dir) and mapping:
        with labels._locked(doc_dir) as data:
            for kind in ("labels", "annotations"):
                data[kind] = [_map_record(r, rx, mapping) for r in data[kind]]
        for path in sorted((doc_dir / quote_pass.MACHINE_DIR).glob("*.json")):
            qp = quote_pass.load_pass(path)
            qp.found = [_map_record(q, rx, mapping) for q in qp.found]
            path.write_text(
                qp.model_dump_json(indent=2, by_alias=True) + "\n", encoding="utf-8"
            )

    if labels.has_text(doc_dir):
        counts = labels.refresh_text(doc_dir)
        for how, n in quote_pass.reanchor_passes(doc_dir).items():
            counts[how] = counts.get(how, 0) + n
    else:
        labels.ensure_text(doc_dir)
        counts = {}
    _clear_found(doc_dir)
    stale = len(lost_records(doc_dir))
    gitops.commit_labels(doc_dir, f"evid: replace {doc_dir.name[:8]} ({stale} stale)")
    return {
        "uuid": doc_dir.name,
        "counts": counts,
        "stale": stale,
        "mapped": len(mapping),
    }


def _clear_found(doc_dir: Path) -> None:
    """A record that was lost and is found again is no longer lost."""
    text, _ = labels.read_text(doc_dir)
    with labels._locked(doc_dir) as data:
        for kind in ("labels", "annotations"):
            for r in data[kind]:
                if (
                    r.get("lost")
                    and r.get("text")
                    and text[r.get("start", 0) : r.get("end", 0)] == r["text"]
                ):
                    r.pop("lost", None)


def _pdf_title(pdf: Path) -> str:
    try:
        import pymupdf

        with pymupdf.open(pdf) as doc:
            return (doc.metadata or {}).get("title", "").strip()
    except Exception:
        return ""


def _set_info(doc_dir: Path, **fields) -> None:
    import yaml

    f = doc_dir / "info.yml"
    data = yaml.safe_load(f.read_text("utf-8")) or {}
    data.update({k: v for k, v in fields.items() if v})
    f.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=True), "utf-8")


# ── stale records ────────────────────────────────────────────────────────────


def lost_records(doc_dir: Path) -> list[dict]:
    """Every lost label, annotation and machine quote of one document."""
    out = []
    if not labels.has_text(doc_dir):
        return out
    data = labels.read(doc_dir)
    for kind in ("labels", "annotations"):
        for r in data[kind]:
            if r.get("lost"):
                out.append(
                    {
                        "kind": kind[:-1],
                        "key": r.get("key") or r.get("id"),
                        "text": r.get("text", ""),
                    }
                )
    for path in sorted((doc_dir / quote_pass.MACHINE_DIR).glob("*.json")):
        for q in quote_pass.load_pass(path).found:
            if q.get("lost"):
                out.append(
                    {
                        "kind": "quote",
                        "key": q.get("key"),
                        "text": q.get("text", ""),
                        "pass": path.stem,
                    }
                )
    return out


def stale(set_dir: Path, uuid: str | None = None) -> list[dict]:
    """[{uuid, title, records: [...]}] for every document of the set with lost records."""
    import yaml

    docs = (
        sorted((Path(set_dir) / "docs").iterdir())
        if (Path(set_dir) / "docs").is_dir()
        else []
    )
    out = []
    for d in docs:
        if uuid and d.name != uuid:
            continue
        recs = lost_records(d)
        if recs:
            try:
                title = (yaml.safe_load((d / "info.yml").read_text("utf-8")) or {}).get(
                    "title", ""
                )
            except OSError:
                title = ""
            out.append({"uuid": d.name, "title": title, "records": recs})
    return out


# ── repair: a model points, the text decides ────────────────────────────────


UNIT_RE = re.compile(r"[^\n.!?]*(?:[.!?]+|\n|$)")


def _units(text: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence or line of TEXT, whitespace trimmed."""
    out = []
    for m in UNIT_RE.finditer(text):
        a, b = m.start(), m.end()
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if b > a:
            out.append((a, b))
    return out


def candidates(needle: str, text: str, n: int = 6) -> list[tuple[int, int, float]]:
    """(start, end, score) of the N passages of TEXT most like NEEDLE: whole sentences or
    lines, and runs of up to three of them (a label can span sentences)."""
    if not needle.strip():
        return []
    units = _units(text)
    spans = {
        (units[i][0], units[j][1])
        for i in range(len(units))
        for j in range(i, min(i + 3, len(units)))
    }
    scored = sorted(
        ((fuzz.ratio(needle, text[a:b]) / 100, a, b) for a, b in spans),
        key=lambda x: (-x[0], x[1]),
    )
    out: list[tuple[int, int, float]] = []
    for s, a, b in scored:
        if len(out) >= n:
            break
        out.append((a, b, s))
    return out


def _ask(prompt: str) -> str:
    cmd = os.environ.get("EVID_REPAIR_CMD") or (
        "claude -p" if shutil.which("claude") else ""
    )
    if not cmd:
        raise RuntimeError(
            "no model to ask: set EVID_REPAIR_CMD (a command reading a prompt on stdin)"
        )
    r = subprocess.run(
        shlex.split(cmd),
        check=False,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"{cmd}: {(r.stderr or r.stdout).strip()[-400:]}")
    return r.stdout


PROMPT = """A label in an anonymised document lost its place after the document was replaced by a
newer version (placeholders such as [PERSON 1] may have been renumbered).

The label's old text:
<<<{old}>>>

Candidate passages from the new version, numbered:
{cands}

Which passage does the label now point at? Answer with JSON only:
{{"choice": <number or null>, "text": "<the exact passage it should cover, copied verbatim from that candidate>"}}
Copy characters exactly; do not paraphrase. Use null if none fits."""


def repair_record(rec: dict, text: str, pages, ask=_ask) -> dict | None:
    """A re-anchored copy of REC, or None. Accepted only when the answer is found verbatim."""
    cands = candidates(rec.get("text", ""), text)
    if not cands:
        return None
    listing = "\n".join(
        f"[{i}] <<<{text[a:b]}>>>" for i, (a, b, _) in enumerate(cands, 1)
    )
    answer = ask(PROMPT.format(old=rec.get("text", ""), cands=listing))
    m = re.search(r"\{.*\}", answer, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    pick, quote = data.get("choice"), str(data.get("text") or "").strip()
    if not pick or not quote:
        return None
    try:
        a, b, _ = cands[int(pick) - 1]
    except (ValueError, IndexError):
        return None
    at = text.find(quote, a, b + len(quote))
    if at < 0:
        at = text.find(quote)
        if at < 0 or text.count(quote) != 1:
            return None  # not the document's own bytes, or ambiguous: leave it stale
    span = make_span(text, at, at + len(quote), pages)
    out = {
        **{
            k: v
            for k, v in rec.items()
            if k not in ("start", "end", "page", "text", "prefix", "suffix", "lost")
        },
        **span,
    }
    out["repaired"] = True
    return out


def repair(doc_dir: Path, ask=_ask) -> dict:
    """Ask the model about every lost label and annotation of one document. Returns counts."""
    doc_dir = Path(doc_dir)
    text, pages = labels.read_text(doc_dir)
    fixed = left = 0
    with labels._locked(doc_dir) as data:
        for kind in ("labels", "annotations"):
            kept = []
            for r in data[kind]:
                if not r.get("lost"):
                    kept.append(r)
                    continue
                new = repair_record(r, text, pages, ask)
                if new:
                    fixed += 1
                    kept.append(new)
                else:
                    left += 1
                    kept.append(r)
            data[kind] = kept
    if fixed:
        gitops.commit_labels(
            doc_dir, f"evid: repair {doc_dir.name[:8]} ({fixed} re-anchored)"
        )
    return {"uuid": doc_dir.name, "repaired": fixed, "stale": left}
