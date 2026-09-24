"""Fast YAML loading for bulk reads.

PyYAML's ``safe_load`` uses the pure-Python loader, which is ~8x slower than the
libyaml-backed ``CSafeLoader`` on the small per-document YAML files evid reads
in bulk (a set switch parses one ``info.yml`` and one ``evid_meta.yml`` per
document). ``load_yaml`` selects the C loader when available and falls back to
the pure-Python one. Output is identical.
"""

from __future__ import annotations

from typing import Any

import yaml

_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def load_yaml(stream: Any) -> Any:
    """Parse *stream* (path/str/file object) with the fastest safe loader."""
    return yaml.load(stream, Loader=_Loader)  # noqa: S506 — _Loader is Safe/CSafeLoader
