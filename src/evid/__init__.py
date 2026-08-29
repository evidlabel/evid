"""evid — evidence management: PDF labeling, vector search, and citation gather."""

from evid.config import ConfigModel, EvidConfig
from evid.models import (
    Document,
    EvidenceSet,
    InfoModel,
    SetType,
    Tag,
    TagItem,
    VecResult,
)

__version__ = "0.4.0"

__all__ = [
    "ConfigModel",
    "Document",
    "EvidConfig",
    "EvidenceSet",
    "InfoModel",
    "SetType",
    "Tag",
    "TagItem",
    "VecResult",
    "__version__",
]
