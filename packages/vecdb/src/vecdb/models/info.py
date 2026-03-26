"""Pydantic model for info.yml metadata."""

from pydantic import BaseModel
from typing import Optional


class DocumentInfo(BaseModel):
    """Metadata from info.yml (used for rich query results)."""
    title: str
    url: Optional[str] = None
    authors: Optional[str] = None
    dates: Optional[str] = None
    label: Optional[str] = None
    uuid: str
    original_name: Optional[str] = None
    tags: Optional[str] = ""
