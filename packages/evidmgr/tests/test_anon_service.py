"""Tests for AnonService (did is mocked — no spaCy required)."""

import pytest
from pathlib import Path
from datetime import datetime, timezone
import yaml

from evidmgr.models import AnonMode, EvidenceSet, SetType
from evidmgr.services.anon_service import AnonService


@pytest.fixture
def anon_set(tmp_path):
    set_dir = tmp_path / "sets" / "test-case"
    (set_dir / "anon").mkdir(parents=True)
    return EvidenceSet(
        name="Test Case",
        slug="test-case",
        path=set_dir,
        set_type=SetType.ANON,
        created=datetime.now(tz=timezone.utc),
    )


def _write_entity_yaml(anon_dir: Path, name: str, entities: list[dict], is_current: bool = False) -> Path:
    path = anon_dir / f"{name}_entities.yml"
    data = {
        "generated": datetime.now(tz=timezone.utc).isoformat(),
        "docs_included": [],
        "language": "da",
        "entities": entities,
    }
    with path.open("w") as f:
        yaml.safe_dump(data, f)
    if is_current:
        (anon_dir / "current").write_text(path.name)
    return path


def test_list_yamls_empty(anon_set):
    svc = AnonService()
    assert svc.list_yamls(anon_set) == []


def test_set_and_get_current(anon_set):
    svc = AnonService()
    entities = [{"original": "Lars Hansen", "variants": [], "entity_type": "PERSON",
                 "placeholder": "[PERSON A]", "fake": ""}]
    path = _write_entity_yaml(anon_set.path / "anon", "20240101T120000", entities)
    svc.set_current(anon_set, path)
    current = svc.get_current_yaml(anon_set)
    assert current is not None
    assert current.is_current
    assert current.entities[0]["original"] == "Lars Hansen"


def test_pseudonymize_real_mode(anon_set):
    svc = AnonService()
    text = "Lars Hansen was assessed on 2024-01-01."
    result = svc.pseudonymize(text, anon_set, AnonMode.REAL)
    assert result == text


def test_pseudonymize_placeholder_mode(anon_set):
    svc = AnonService()
    entities = [{"original": "Lars Hansen", "variants": ["L. Hansen"],
                 "entity_type": "PERSON", "placeholder": "[PERSON A]", "fake": ""}]
    _write_entity_yaml(anon_set.path / "anon", "20240101T120000", entities, is_current=True)
    text = "Lars Hansen and L. Hansen were present."
    result = svc.pseudonymize(text, anon_set, AnonMode.PLACEHOLDER)
    assert "[PERSON A]" in result
    assert "Lars Hansen" not in result
    assert "L. Hansen" not in result


def test_pseudonymize_fake_mode(anon_set):
    svc = AnonService()
    entities = [{"original": "Lars Hansen", "variants": [],
                 "entity_type": "PERSON", "placeholder": "[PERSON A]", "fake": "Martin Andersen"}]
    _write_entity_yaml(anon_set.path / "anon", "20240101T120000", entities, is_current=True)
    text = "Lars Hansen filed the claim."
    result = svc.pseudonymize(text, anon_set, AnonMode.FAKE)
    assert "Martin Andersen" in result
    assert "Lars Hansen" not in result


def test_pseudonymize_fake_fallback_to_placeholder(anon_set):
    """If fake is empty, falls back to placeholder."""
    svc = AnonService()
    entities = [{"original": "Lars Hansen", "variants": [],
                 "entity_type": "PERSON", "placeholder": "[PERSON A]", "fake": ""}]
    _write_entity_yaml(anon_set.path / "anon", "20240101T120000", entities, is_current=True)
    text = "Lars Hansen submitted."
    result = svc.pseudonymize(text, anon_set, AnonMode.FAKE)
    assert "[PERSON A]" in result


def test_pseudonymize_no_current_yaml_returns_text(anon_set):
    svc = AnonService()
    text = "Some sensitive text."
    assert svc.pseudonymize(text, anon_set, AnonMode.PLACEHOLDER) == text


def test_did_yaml_conversion():
    did_yaml = """
PERSON:
  - id: "Lars Hansen"
    variants: ["L. Hansen"]
LOCATION:
  - id: "Roskildevej 44"
    variants: []
"""
    entities = AnonService._did_yaml_to_entities(did_yaml, ["uuid-1"])
    assert len(entities) == 2
    persons = [e for e in entities if e["entity_type"] == "PERSON"]
    assert persons[0]["placeholder"] == "[PERSON A]"
    locs = [e for e in entities if e["entity_type"] == "LOCATION"]
    assert locs[0]["placeholder"] == "[ADDRESS A]"
