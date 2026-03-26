"""evidmgr data models — single source of truth for all packages."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class SetType(str, Enum):
    NORMAL = "normal"
    ANON = "anon"


class SourceType(str, Enum):
    LAW = "law"
    GUIDELINE = "guideline"
    PAPER = "paper"
    CASE = "case"
    OTHER = "other"


class AnonMode(str, Enum):
    REAL = "real"
    PLACEHOLDER = "placeholder"
    FAKE = "fake"


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class NameOrigin(str, Enum):
    DANISH = "danish"
    ARABIC = "arabic"
    SOMALI = "somali"
    TURKISH = "turkish"
    EASTERN_EUROPEAN = "eastern_european"
    UNKNOWN = "unknown"


@dataclass
class EvidenceSet:
    name: str
    slug: str
    path: Path
    set_type: SetType
    created: datetime
    description: str = ""
    anon_language: str = "da"


@dataclass
class Document:
    uuid: str
    path: Path
    label: str
    tags: list[str]
    source_type: SourceType
    added: datetime
    indexed: bool = False
    anon_pending: bool = False
    notes: str = ""
    source_url: str = ""


@dataclass
class EntityDetected:
    gender: Gender = Gender.UNKNOWN
    name_origin: NameOrigin = NameOrigin.UNKNOWN
    age: int | None = None


@dataclass
class EntityEntry:
    original: str
    variants: list[str]
    entity_type: str  # PERSON | ADDRESS | CPR | ...
    placeholder: str
    detected: EntityDetected | None = None
    # profiles: {"same": "Erik Madsen", "gender_inverted": "Rikke Madsen", …}
    profiles: dict[str, str] = field(default_factory=dict)


@dataclass
class AnonYaml:
    path: Path
    generated: datetime
    docs_included: list[str]
    is_current: bool
    entities: list[EntityEntry]


@dataclass
class FakeProfile:
    key: str  # "same" | "gender_inverted" | "ethnicity_inverted" | "both_inverted"
    label: str
    target_gender: Gender
    target_origin: NameOrigin


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


def make_seed(doc_uuid: str, entity_idx: int, profile_name: str) -> int:
    """Deterministic seed keyed on (doc_uuid, entity_idx, profile_name)."""
    key = f"{doc_uuid}:{entity_idx}:{profile_name}".encode()
    return int.from_bytes(hashlib.md5(key).digest()[:4], "little")  # noqa: S324


def seeded_rng(doc_uuid: str, entity_idx: int, profile_name: str) -> random.Random:
    return random.Random(make_seed(doc_uuid, entity_idx, profile_name))
