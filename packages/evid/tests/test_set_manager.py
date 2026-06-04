"""Tests for SetManager."""

import pytest
from evid.models import SetType
from evid.services.set_manager import SetManager


@pytest.fixture
def sm(tmp_path):
    return SetManager(tmp_path)


def test_create_and_load_set(sm):
    s = sm.create_set("Hansen Case 2024", set_type=SetType.NORMAL)
    assert s.slug == "hansen-case-2024"
    assert s.set_type == SetType.NORMAL
    loaded = sm.load_set("hansen-case-2024")
    assert loaded.name == "Hansen Case 2024"


def test_create_set_dirs(sm, tmp_path):
    sm.create_set("Test Set")
    set_dir = tmp_path / "sets" / "test-set"
    assert (set_dir / "docs").is_dir()
    assert (set_dir / "vecdb").is_dir()
    assert not (set_dir / "anon").exists()  # normal set has no anon dir


def test_create_anon_set_has_anon_dir(sm, tmp_path):
    sm.create_set("Anon Set", set_type=SetType.ANON)
    assert (tmp_path / "sets" / "anon-set" / "anon").is_dir()


def test_list_sets(sm):
    sm.create_set("Alpha")
    sm.create_set("Beta")
    sets = sm.list_sets()
    slugs = [s.slug for s in sets]
    assert "alpha" in slugs
    assert "beta" in slugs


def test_duplicate_slug_raises(sm):
    sm.create_set("My Set")
    with pytest.raises(FileExistsError):
        sm.create_set("My Set")


def test_load_nonexistent_raises(sm):
    with pytest.raises(FileNotFoundError):
        sm.load_set("does-not-exist")


def test_delete_set(sm):
    sm.create_set("Temp Set")
    sm.delete_set("temp-set")
    with pytest.raises(FileNotFoundError):
        sm.load_set("temp-set")


def test_update_set_meta(sm):
    sm.create_set("Original Name")
    updated = sm.update_set_meta("original-name", description="Updated desc")
    assert updated.description == "Updated desc"
    loaded = sm.load_set("original-name")
    assert loaded.description == "Updated desc"


def test_list_documents_empty(sm):
    sm.create_set("Empty")
    docs = sm.list_documents("empty")
    assert docs == []
