"""Models for recipe YAML validation."""

from pydantic import BaseModel, Field


class GuideChild(BaseModel):
    id: str
    label: str
    add_layers: list[str] = Field(default_factory=list)
    add_questioning: list[str] = Field(default_factory=list)


class GuideItem(BaseModel):
    id: str
    label: str
    add_layers: list[str] = Field(default_factory=list)
    add_questioning: list[str] = Field(default_factory=list)
    children: list[GuideChild] = Field(default_factory=list)


class QuestioningLine(BaseModel):
    id: str
    name: str
    file: str | None = None  # path relative to domain YAML
    body: str | None = None  # inline fallback


class Layer(BaseModel):
    id: str
    title: str | None = None
    evidence: list[str] = Field(default_factory=list)
    grounding: str | None = None  # path relative to domain YAML
    # Future: import: Optional[str] = None


class Recipe(BaseModel):
    id: str
    title: str
    output_filename: str | None = None
    guide: list[GuideItem] = Field(default_factory=list)
    questioning: list[QuestioningLine] = Field(default_factory=list)
    default_questioning: list[str] = Field(default_factory=list)
    final_question: str | None = None  # inline string, not a file path
    layers: list[Layer] = Field(default_factory=list)
