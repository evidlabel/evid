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


def test_create_set_adopts_precreated_slug_dir(sm, tmp_path):
    """mkdir-then-create must write set.yml so list_sets can see the slug."""
    slug_dir = tmp_path / "sets" / "emilierasmus"
    (slug_dir / "docs").mkdir(parents=True)
    s = sm.create_set("emilierasmus")
    assert s.slug == "emilierasmus"
    assert (slug_dir / "set.yml").is_file()
    assert [x.slug for x in sm.list_sets()] == ["emilierasmus"]


def test_create_set_adopts_slug_dir_that_already_has_docs(sm, tmp_path):
    slug_dir = tmp_path / "sets" / "emilierasmus"
    doc = slug_dir / "docs" / "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    doc.mkdir(parents=True)
    (doc / "info.yml").write_text("uuid: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n")
    s = sm.create_set("emilierasmus")
    assert (slug_dir / "set.yml").is_file()
    assert (slug_dir / "docs" / "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee").is_dir()
    assert sm.load_set("emilierasmus").slug == s.slug


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


def test_list_documents_requires_info_yml(sm, tmp_path):
    sm.create_set("Case")
    real = tmp_path / "sets" / "case" / "docs" / "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    real.mkdir(parents=True)
    (real / "info.yml").write_text("uuid: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n")
    junk = tmp_path / "sets" / "case" / "docs" / "sets"
    junk.mkdir()
    docs = sm.list_documents("case")
    assert [d.name for d in docs] == ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]
