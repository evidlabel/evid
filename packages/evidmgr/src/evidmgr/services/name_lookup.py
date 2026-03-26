"""Demographic inversion — name generation for fake identity profiles.

Uses bundled name lists (data/names/) + seeded RNG for reproducibility.
Gender detection via gender_guesser (optional dep).
"""

from __future__ import annotations

import importlib.resources
import logging
from functools import lru_cache

from evidmgr.models import FakeProfile, Gender, NameOrigin, seeded_rng

logger = logging.getLogger(__name__)

# All supported profile keys and their dimensions
STANDARD_PROFILES: list[FakeProfile] = []  # populated below


def _build_standard_profiles(detected_gender: Gender, detected_origin: NameOrigin) -> list[FakeProfile]:
    """Build the four standard profiles based on detected demographics."""
    inv_gender = _invert_gender(detected_gender)
    inv_origin = _invert_origin(detected_origin)
    return [
        FakeProfile(
            key="same",
            label="Same demographics",
            target_gender=detected_gender if detected_gender != Gender.UNKNOWN else Gender.NEUTRAL,
            target_origin=detected_origin if detected_origin != NameOrigin.UNKNOWN else NameOrigin.DANISH,
        ),
        FakeProfile(
            key="gender_inverted",
            label="Gender inverted",
            target_gender=inv_gender,
            target_origin=detected_origin if detected_origin != NameOrigin.UNKNOWN else NameOrigin.DANISH,
        ),
        FakeProfile(
            key="ethnicity_inverted",
            label="Ethnicity inverted",
            target_gender=detected_gender if detected_gender != Gender.UNKNOWN else Gender.NEUTRAL,
            target_origin=inv_origin,
        ),
        FakeProfile(
            key="both_inverted",
            label="Both inverted",
            target_gender=inv_gender,
            target_origin=inv_origin,
        ),
    ]


def _invert_gender(g: Gender) -> Gender:
    if g == Gender.MALE:
        return Gender.FEMALE
    if g == Gender.FEMALE:
        return Gender.MALE
    return Gender.NEUTRAL


def _invert_origin(o: NameOrigin) -> NameOrigin:
    """Default inversion: danish→arabic, others→danish."""
    if o == NameOrigin.DANISH:
        return NameOrigin.ARABIC
    return NameOrigin.DANISH


@lru_cache(maxsize=32)
def _load_names(origin: NameOrigin, gender: Gender, part: str) -> list[str]:
    """Load name list from bundled data. Returns empty list on error."""
    origin_dir = origin.value  # e.g. "danish"
    if gender == Gender.MALE:
        filename = f"{part}_first.txt" if part == "male" else "last.txt"
        if part in {"first", "male_first"}:
            filename = "male_first.txt"
        elif part == "last":
            filename = "last.txt"
        else:
            filename = "male_first.txt"
    elif gender == Gender.FEMALE:
        if part in {"first", "female_first"}:
            filename = "female_first.txt"
        elif part == "last":
            filename = "last.txt"
        else:
            filename = "female_first.txt"
    else:
        # Neutral: mix male + female first names
        if part == "last":
            filename = "last.txt"
        else:
            male = _load_names(origin, Gender.MALE, "first")
            female = _load_names(origin, Gender.FEMALE, "first")
            return male + female

    try:
        pkg = importlib.resources.files("evidmgr.data.names") / origin_dir
        content = (pkg / filename).read_text(encoding="utf-8")
        return [line.strip() for line in content.splitlines() if line.strip()]
    except Exception:
        logger.warning("Name list not found: %s/%s/%s", origin_dir, gender, part)
        return ["Person"]


def generate_fake_name(
    entity_idx: int,
    doc_uuid: str,
    target_gender: Gender,
    target_origin: NameOrigin,
    profile_name: str,
) -> str:
    """Generate a deterministic fake name for a given profile key."""
    rng = seeded_rng(doc_uuid, entity_idx, profile_name)
    first_pool = _load_names(target_origin, target_gender, "first")
    last_pool = _load_names(target_origin, target_gender, "last")
    first = rng.choice(first_pool) if first_pool else "Unknown"
    last = rng.choice(last_pool) if last_pool else "Person"
    return f"{first} {last}"


def detect_gender_from_name(name: str) -> Gender:
    """Detect gender from a first name using gender_guesser (optional)."""
    try:
        import gender_guesser.detector as gd  # noqa: PLC0415

        first_name = name.split()[0] if name.strip() else name
        d = gd.Detector(case_sensitive=False)
        result = d.get_gender(first_name)
        if result in {"male", "mostly_male"}:
            return Gender.MALE
        if result in {"female", "mostly_female"}:
            return Gender.FEMALE
        return Gender.UNKNOWN
    except ImportError:
        return Gender.UNKNOWN


def generate_all_profiles(
    entity_idx: int,
    doc_uuid: str,
    detected_gender: Gender,
    detected_origin: NameOrigin,
) -> dict[str, str]:
    """Generate name replacements for all four standard profiles."""
    profiles = _build_standard_profiles(detected_gender, detected_origin)
    return {
        p.key: generate_fake_name(entity_idx, doc_uuid, p.target_gender, p.target_origin, p.key)
        for p in profiles
    }
