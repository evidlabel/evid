"""Pydantic models for entity configuration."""

from pydantic import BaseModel, Field


class Entity(BaseModel):
    """Model for an individual entity with variants."""

    id: str
    variants: list[str]
    pattern: str | None = None  # Optional pattern for numbers


class Config(BaseModel):
    """Overall configuration model for entities."""

    person: list[Entity] = Field(alias="PERSON", default_factory=list)
    email_address: list[Entity] = Field(alias="EMAIL_ADDRESS", default_factory=list)
    location: list[Entity] = Field(alias="LOCATION", default_factory=list)
    phone_number: list[Entity] = Field(alias="PHONE_NUMBER", default_factory=list)
    date_number: list[Entity] = Field(alias="DATE_NUMBER", default_factory=list)
    id_number: list[Entity] = Field(alias="ID_NUMBER", default_factory=list)
    code_number: list[Entity] = Field(alias="CODE_NUMBER", default_factory=list)
    general_number: list[Entity] = Field(alias="GENERAL_NUMBER", default_factory=list)
    url: list[Entity] = Field(alias="URL", default_factory=list)
