"""Build a document's label/ and pass/ for tests (evid 0.7 layout)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from evid.core import labels as lab

if TYPE_CHECKING:
    from pathlib import Path


def label_doc(
    doc_dir: Path, labels=(), quotes=(), filler: str = "Header line."
) -> Path:
    """Write label/text.txt + pages.json holding each passage on its page, then the records.

    *labels*: dicts with key, text, note (optional), page (optional, default 1).
    *quotes*: dicts with text and page (optional): machine quotes, in one pass.
    """
    by_page: dict[int, list[str]] = {}
    for item in [*labels, *quotes]:
        by_page.setdefault(int(item.get("page") or item.get("opage") or 1), []).append(
            item["text"]
        )
    by_page = by_page or {1: []}
    text, pages = "", []
    for page in sorted(by_page):
        pages.append([len(text), page])
        text += (
            f"{filler} Page {page}.\n" + "".join(t + "\n" for t in by_page[page]) + "\n"
        )
    lab._write_text(doc_dir, text, pages)
    for item in labels:
        span, _, _ = lab.span_of(doc_dir, item["text"])
        lab.add_label(doc_dir, span, item["key"], note=item.get("note", ""))
    if quotes:
        from evid.core.quote_extract import QuoteCandidate, QuoteResult
        from evid.core.quote_pass import record_pass

        results = []
        for n, q in enumerate(quotes, 1):
            span, _, _ = lab.span_of(doc_dir, q["text"])
            results.append(
                QuoteResult(
                    candidate=q["text"],
                    matched=True,
                    score=1.0,
                    key=f"x:q{n}",
                    page=span["page"],
                    span={**span, "key": f"q{n}", "score": 1.0},
                )
            )
        record_pass(
            doc_dir,
            job=q.get("job", "test pass"),
            model=None,
            quotes=[QuoteCandidate(candidate=q["text"]) for q in quotes],
            results=results,
        )
    return doc_dir
