"""Field values Hayagriva (Typst's bibliography) accepts, and labquote reads well.

- ``date``: ISO only (``2018-02-20``, ``2018-02``, ``2018``). evid's info.yml
  often holds ``20-02-2018``; Typst rejects that ("date format unknown") and
  labquote would read its year as "20-0".
- ``author``: a comma list of several people (``A B, C D, E F``) is read by
  Hayagriva as one "Last, First, Suffix" name ("too many parts"). It is written
  as ``A B and C D and E F``, which Hayagriva parses and labquote shows as
  "A & B" / "A et al.". A single ``Last, First`` stays as it is.
  An organisation whose name has a comma is written in braces in info.yml
  (``{Institut for Menneskerettigheder, Danmark}``): it is kept as one name,
  braces removed. Several may be listed: ``{A, B}, {C}``.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_ISO = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_DMY = re.compile(r"^(\d{1,2})[-./](\d{1,2})[-./](\d{4})$")
_BRACED = re.compile(r"\{([^{}]*)\}")
_YMD = re.compile(r"^(\d{4})[./](\d{1,2})[./](\d{1,2})$")


def hayagriva_date(value: object) -> str | None:
    """The first date in *value* as ISO, or None when none can be read."""
    if value is None:
        return None
    for part in re.split(r"[,;]| og | and ", str(value)):
        s = part.strip()
        if not s:
            continue
        if _ISO.match(s):
            return s
        m = _DMY.match(s)
        if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(1)) <= 31:
            return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        m = _YMD.match(s)
        if m and 1 <= int(m.group(2)) <= 12:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    logger.warning("Leaving out a date Hayagriva cannot read: %r", value)
    return None


def braced_names(value: object) -> list[str]:
    """The names in ``{A, B}, {C}`` when *value* is only braced names, else []."""
    s = " ".join(str(value or "").split())
    if not s.startswith("{"):
        return []
    names = [n.strip() for n in _BRACED.findall(s) if n.strip()]
    return names if names and _BRACED.sub("", s).strip(" ,;") == "" else []


def hayagriva_author_field(value: object) -> str | dict | list | None:
    """The ``author`` value for a Hayagriva YAML entry.

    Braced organisations become person dicts (``{name: …}``), which Hayagriva
    never splits at a comma and labquote reads by ``name``. Anything else is
    :func:`hayagriva_author`.
    """
    orgs = braced_names(value)
    if orgs:
        people = [{"name": n} for n in orgs]
        return people[0] if len(people) == 1 else people
    return hayagriva_author(value)


def hayagriva_author(value: object) -> str | None:
    """Authors as Hayagriva reads them (see the module docstring)."""
    if value is None:
        return None
    if isinstance(value, list):
        names = [str(v).strip() for v in value if str(v).strip()]
        return " and ".join(names) or None
    s = " ".join(str(value).split())
    if not s:
        return None
    orgs = braced_names(s)
    if orgs:
        return " and ".join(orgs)
    parts = [p.strip() for p in s.split(",") if p.strip()]
    several_people = len(parts) > 2 or (
        len(parts) == 2 and all(" " in p for p in parts)
    )
    return " and ".join(parts) if several_people else s
