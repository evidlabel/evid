from pydantic import BaseModel, Field
from pathlib import Path


class InfoModel(BaseModel):
    original_name: str = Field(..., description="Original file name")
    uuid: str = Field(..., description="Unique identifier")
    time_added: str = Field(..., description="Date added")
    dates: str = Field(..., description="Document dates")
    title: str = Field(..., description="Document title")
    authors: str = Field(..., description="Authors")
    tags: str = Field(default="", description="Tags")
    label: str = Field(..., description="Label")
    url: str = Field(default="", description="Source URL")


class ConfigModel(BaseModel):
    default_dir: str = Field(default_factory=lambda: str(Path("~/Documents/evid").expanduser()))
    editor: str = "code"
    directory: str = "code"
    latex: str = "pdflatex {file}"
