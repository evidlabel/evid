"""evidmgr data models — single source of truth for all packages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class SetType(StrEnum):
    NORMAL = "normal"


@dataclass
class EvidenceSet:
    name: str
    slug: str
    path: Path
    set_type: SetType
    created: datetime
    description: str = ""


@dataclass
class Document:
    uuid: str
    path: Path
    label: str
    tags: list[str]
    added: datetime
    indexed: bool = False
    notes: str = ""
    source_url: str = ""


@dataclass
class TagItem:
    set_slug: str
    doc_uuid: str
    chunks: list[int] | None = None  # None = whole document


@dataclass
class Tag:
    name: str  # "hansen-case-2024.psych"
    owner_set: str
    created: datetime
    items: list[TagItem] = field(default_factory=list)


@dataclass
class VecResult:
    doc: Document
    chunk_text: str
    score: float
    chunk_idx: int
    char_start: int
