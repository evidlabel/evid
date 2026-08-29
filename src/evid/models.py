"""evidmgr data models — single source of truth for all packages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


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


def _join_if_list(v: object) -> str:
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v) if v is not None else ""


class InfoModel(BaseModel):
    """Model for document info metadata."""

    model_config = {"populate_by_name": True}

    original_name: str = Field(default="", description="Original file name")
    uuid: str = Field(..., description="Unique identifier")
    time_added: str = Field(default="", description="Date added")
    dates: str | list = Field(default="", description="Document dates")
    title: str = Field(default="", description="Document title")
    authors: str | list = Field(default="", alias="author", description="Authors")
    tags: str | list = Field(default="", description="Tags")
    label: str = Field(default="", description="Label")
    url: str = Field(default="", description="Source URL")

    @field_validator("dates", "authors", "tags", mode="before")
    @classmethod
    def coerce_list_to_str(cls, v: object) -> str:
        return _join_if_list(v)

    @model_validator(mode="before")
    @classmethod
    def handle_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Accept both 'author' and 'authors'; 'authors' wins if both present
            if "authors" not in data and "author" in data:
                data = dict(data, authors=data["author"])
            # Fall back label to title or original_name
            if not data.get("label"):
                data = dict(
                    data, label=data.get("title") or data.get("original_name", "")
                )
        return data
