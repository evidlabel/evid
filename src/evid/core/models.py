from pydantic import BaseModel, Field

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
