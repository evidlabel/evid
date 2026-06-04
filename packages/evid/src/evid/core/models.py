"""Data models for evid."""

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


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


class ConfigModel(BaseModel):
    """Model for configuration settings."""

    default_dir: str = Field(default_factory=lambda: "~/Documents/evid")
    editor: str = "code"
    directory: str = "code"
    latex: str = "pdflatex {file}"
