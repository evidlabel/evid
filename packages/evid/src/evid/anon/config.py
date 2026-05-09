"""Configuration handling for Anonymizer (YAML generation and loading)."""

import io

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from .models import Config, Entity

FIELD_MAPPING = {
    "person": "PERSON",
    "email_address": "EMAIL_ADDRESS",
    "location": "LOCATION",
    "phone_number": "PHONE_NUMBER",
    "date_number": "DATE_NUMBER",
    "id_number": "ID_NUMBER",
    "code_number": "CODE_NUMBER",
    "general_number": "GENERAL_NUMBER",
    "url": "URL",
}


def to_plain(obj):
    """Convert ruamel.yaml objects to plain Python types."""
    if hasattr(obj, "items") and callable(obj.items):  # dict-like (CommentedMap)
        return {k: to_plain(v) for k, v in obj.items()}
    if hasattr(obj, "__iter__") and not isinstance(
        obj, str
    ):  # list-like (CommentedSeq)
        return [to_plain(item) for item in obj]
    return obj


def generate_yaml(anonymizer) -> str:
    """Generate YAML configuration from detected entities with all strings quoted."""
    data = anonymizer.entities.model_dump(by_alias=True, exclude_none=True)

    def quote_strings(obj):
        if isinstance(obj, dict):
            return {k: quote_strings(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [quote_strings(item) for item in obj]
        if isinstance(obj, str):
            return DoubleQuotedScalarString(obj)
        return obj

    quoted_data = quote_strings(data)

    yaml_instance = YAML()
    stream = io.StringIO()
    yaml_instance.dump(quoted_data, stream)
    return stream.getvalue()


def load_replacements(anonymizer, config):
    """Load replacements from YAML config using explicit mapping for robustness."""
    config = to_plain(config)
    data = {}
    for alias in FIELD_MAPPING.values():
        if alias in config:
            entities_data = config[alias]
            if isinstance(entities_data, list):
                try:
                    validated_entities = [
                        Entity.model_validate(item) for item in entities_data
                    ]
                    data[alias] = validated_entities
                except Exception:
                    data[alias] = []
            else:
                data[alias] = []
        else:
            data[alias] = []
    try:
        anonymizer.entities = Config.model_validate(data)
    except Exception:
        anonymizer.entities = Config()
