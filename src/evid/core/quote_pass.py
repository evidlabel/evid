"""Machine-pass ledger: persist and load non-citable quote-job records.

Each ``evid doc quote`` invocation writes one JSON file under ``machine/``
next to ``machine.hayagriva``. Hayagriva stays the citation store; these
files are the job history — timestamp, a natural-language job description,
which model ran the pass, and per-candidate outcomes (including skips).

The verbatim quote body is not stored here. Aggregators join on ``key``.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from evid.core.quote_extract import QuoteCandidate, QuoteResult

logger = logging.getLogger(__name__)

MACHINE_DIR = "machine"
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
