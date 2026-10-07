"""Machine passes: one JSON file per ``evid doc quote`` run, under ``pass/``.

A pass holds the job (description, model, time), every candidate's outcome,
and the quotes it found — as spans over the document's canonical text
(``label/text.txt``), in the same shape as human labels, keyed ``qN``.
Hayagriva for labquote is produced from these at gather time.

(Before evid 0.7 the ledger lived in ``machine/`` and the quotes in
``machine.hayagriva``; ``evid set migrate-labels`` moves them here.)

Each ``evid doc quote`` invocation writes one JSON file under ``machine/``
next to ``machine.hayagriva``. Hayagriva stays the citation store; these
files are the job history — timestamp, a natural-language job description,
which model ran the pass, and per-candidate outcomes (including skips).

The verbatim quote body is not stored here. Aggregators join on ``key``.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from evid.core.quote_extract import QuoteCandidate, QuoteResult

logger = logging.getLogger(__name__)

MACHINE_DIR = "pass"
SCHEMA = 1
MODEL_ENV = "EVID_QUOTE_MODEL"


class PassResult(BaseModel):
    """Outcome of one candidate. No verbatim quote body."""

    candidate: str
    matched: bool
    score: float
    key: str | None = None
    page: int | None = None


class QuotePass(BaseModel):
    """One ``doc quote`` invocation, as stored under ``machine/``."""

    id: str
    timestamp: str
    schema_version: int = Field(default=SCHEMA, alias="schema")
    model: str | None = None
    evid_version: str
    job: str | None = None
    quotes: list[QuoteCandidate] = Field(default_factory=list)
    results: list[PassResult] = Field(default_factory=list)
    found: list[dict] = Field(
        default_factory=list
    )  # quotes as spans: key qN, start, end, page, text, score

    model_config = {"populate_by_name": True}


def resolve_pass_meta(
    *,
    job: str | None = None,
    model: str | None = None,
    from_search: str | None = None,
    quotes_file: object | None = None,
) -> tuple[str | None, str | None]:
    """Pick the job description and model for a pass.

    *job*: ``--job``, else the ``--from-search`` string, else ``quotes_file.job``.
    *model*: ``--model``, else ``quotes_file.model``, else ``EVID_QUOTE_MODEL``.
    Missing stays ``None`` — never guessed.
    """
    file_job = getattr(quotes_file, "job", None) if quotes_file is not None else None
    file_model = (
        getattr(quotes_file, "model", None) if quotes_file is not None else None
    )
    resolved_job = job or from_search or file_job or None
    env_model = os.environ.get(MODEL_ENV) or None
    resolved_model = model or file_model or env_model
    return resolved_job, resolved_model


def record_pass(
    doc_dir: Path,
    *,
    job: str | None,
    model: str | None,
    quotes: list[QuoteCandidate],
    results: list[QuoteResult],
    now: datetime | None = None,
) -> Path:
    """Write one pass JSON under ``doc_dir/machine/`` and return its path."""
    when = now or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    when = when.astimezone(UTC)
    ts_iso = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = when.strftime("%Y-%m-%dT%H-%M-%SZ")
    pass_id = f"{ts_file}_{secrets.token_hex(2)}"

    from evid import __version__ as evid_version

    payload = QuotePass(
        id=pass_id,
        timestamp=ts_iso,
        schema_version=SCHEMA,
        model=model,
        evid_version=evid_version,
        job=job,
        quotes=list(quotes),
        results=[
            PassResult(
                candidate=r.candidate,
                matched=r.matched,
                score=r.score,
                key=r.key,
                page=r.page,
            )
            for r in results
        ],
        found=[r.span for r in results if r.matched and r.span],
    )
    dest = doc_dir / MACHINE_DIR
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{pass_id}.json"
    path.write_text(
        payload.model_dump_json(indent=2, by_alias=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_pass(path: Path) -> QuotePass:
    """Load and validate one pass file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return QuotePass.model_validate(raw)


def list_passes(doc_dir: Path) -> list[QuotePass]:
    """Return passes in this doc, oldest first. Missing dir → empty list."""
    folder = doc_dir / MACHINE_DIR
    if not folder.is_dir():
        return []
    out: list[QuotePass] = []
    for p in folder.glob("*.json"):
        try:
            out.append(load_pass(p))
        except Exception:
            logger.warning("Could not load machine pass %s", p, exc_info=True)
    out.sort(key=lambda qp: qp.timestamp)
    return out


def pass_summaries(doc_dir: Path) -> list[dict]:
    """List metadata only — no candidate or quote text."""
    return [
        {
            "id": qp.id,
            "timestamp": qp.timestamp,
            "model": qp.model,
            "job": qp.job,
            "matched": sum(1 for r in qp.results if r.matched),
            "tried": len(qp.results),
        }
        for qp in list_passes(doc_dir)
    ]


def next_quote_number(doc_dir: Path) -> int:
    """1 + the highest ``qN`` among the document's passes."""
    n = 0
    for qp in list_passes(doc_dir):
        for q in qp.found:
            m = re.fullmatch(r"q(\d+)", str(q.get("key", "")))
            if m:
                n = max(n, int(m.group(1)))
    return n + 1


def note_quote(
    doc_dir: Path,
    key: str,
    text: str,
    by: str = "you",
    pass_id: str | None = None,
) -> dict:
    """Append a dated note to the machine quote ``key``.

    ``pass_id`` limits the search to that pass. KeyError when the quote is
    missing, ValueError when the note is empty. The note stays on the quote
    across a re-anchor.
    """
    text = (text or "").strip()
    if not text:
        msg = "the note is empty"
        raise ValueError(msg)
    doc_dir = Path(doc_dir)
    folder = doc_dir / MACHINE_DIR
    if not folder.is_dir():
        msg = f"no machine quote {key!r}"
        raise KeyError(msg)
    note = {
        "at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "by": by,
        "text": text,
    }
    lock = doc_dir / ".labels.lock"
    with lock.open("a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            return _append_quote_note(folder, key, note, pass_id)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _append_quote_note(folder: Path, key: str, note: dict, pass_id: str | None) -> dict:
    for path in sorted(folder.glob("*.json")):
        qp = load_pass(path)
        if pass_id and qp.id != pass_id:
            continue
        rec = next(
            (q for q in qp.found if q.get("key") == key and not q.get("lost")),
            None,
        )
        if rec is None:
            continue
        rec.setdefault("notes", []).append(note)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            qp.model_dump_json(indent=2, by_alias=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
        return dict(rec)
    msg = f"no machine quote {key!r}"
    raise KeyError(msg)


def found_with_notes(qp: QuotePass) -> list[dict]:
    """Found spans, each carrying its candidate note when the pass recorded one.

    The note stays on that quote. A pass does not write a separate annotation
    for the pass as a whole.
    """
    by_key: dict[str, str] = {}
    for cand, res in zip(qp.quotes, qp.results, strict=False):
        text = (cand.note or "").strip()
        if not text or not res.key:
            continue
        by_key[res.key] = text
        by_key[res.key.rsplit(":", 1)[-1]] = text
    out: list[dict] = []
    for raw in qp.found:
        span = dict(raw)
        note = by_key.get(str(span.get("key") or ""), "")
        notes = [dict(n) for n in span.get("notes") or []]
        if note and note not in {n.get("text") for n in notes}:
            notes.insert(0, {"at": qp.timestamp, "by": "pass", "text": note})
            span["notes"] = notes
        out.append(span)
    return out


def found_quotes(doc_dir: Path) -> list[dict]:
    """Every quote of every pass, oldest pass first, each with its pass id and job."""
    out = []
    for qp in list_passes(doc_dir):
        out.extend(
            {**q, "pass": qp.id, "job": qp.job, "model": qp.model}
            for q in found_with_notes(qp)
        )
    return out


def reanchor_passes(doc_dir: Path) -> dict[str, int]:
    """Re-anchor every pass quote on the (re-extracted) canonical text."""
    from evid.core import labels
    from evid.core.spans import reanchor

    text, pages = labels.read_text(doc_dir)
    counts: dict[str, int] = {}
    for path in sorted((doc_dir / MACHINE_DIR).glob("*.json")):
        qp = load_pass(path)
        kept = []
        for q in qp.found:
            new, how = reanchor(q, text, pages)
            counts[how] = counts.get(how, 0) + 1
            kept.append(new or {**q, "lost": True})
        qp.found = kept
        path.write_text(
            qp.model_dump_json(indent=2, by_alias=True) + "\n", encoding="utf-8"
        )
    return counts
