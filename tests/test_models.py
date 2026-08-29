"""Tests for evidmgr.models."""

from datetime import UTC, datetime
from pathlib import Path

from evid.config import ConfigModel
from evid.models import (
    Document,
    EvidenceSet,
    InfoModel,
    SetType,
)


def test_enums_have_expected_values():
    assert SetType.NORMAL == "normal"


def test_evidence_set_defaults():
    es = EvidenceSet(
        name="Test",
        slug="test",
        path=Path("/tmp/test"),
        set_type=SetType.NORMAL,
        created=datetime.now(tz=UTC),
    )
    assert es.description == ""


def test_document_defaults():
    doc = Document(
        uuid="abc",
        path=Path("/tmp"),
        label="Test",
        tags=[],
        added=datetime.now(tz=UTC),
    )
    assert not doc.indexed
    assert doc.notes == ""


def test_info_model_lives_in_evid_models():
    info = InfoModel(uuid="u1", title="T", tags=["a", "b"])
    assert info.uuid == "u1"
    assert info.tags == "a, b"
    assert info.label == "T"  # falls back from title when label empty


def test_config_model_lives_in_evid_config():
    cfg = ConfigModel()
    assert cfg.editor == "code"
    assert cfg.default_dir == "~/Documents/evid"
