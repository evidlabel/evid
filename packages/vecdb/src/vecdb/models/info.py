"""Pydantic model for info.yml metadata."""

from pydantic import BaseModel


class DocumentInfo(BaseModel):
    """Metadata from info.yml (used for rich query results)."""

    title: str
    url: str | None = None
    authors: str | None = None
    dates: str | None = None
    label: str | None = None
    uuid: str
    original_name: str | None = None
    tags: str | None = ""
