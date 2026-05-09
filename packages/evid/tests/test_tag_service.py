"""Tests for TagService."""

import pytest
from evid.models import TagItem
from evid.services.tag_service import TagService


@pytest.fixture
def ts(tmp_path):
    return TagService(tmp_path)


def test_create_and_get_tag(ts):
    ts.create_tag("hansen.psych", owner_set="hansen-case")
    tag = ts.get_tag("hansen.psych")
    assert tag.name == "hansen.psych"
    assert tag.owner_set == "hansen-case"


def test_list_tags_empty(ts):
    assert ts.list_tags() == []


def test_list_tags_filtered_by_owner(ts):
    ts.create_tag("case1.psych", owner_set="case1")
    ts.create_tag("case2.liability", owner_set="case2")
    case1_tags = ts.list_tags(owner_set="case1")
    assert len(case1_tags) == 1
    assert case1_tags[0].name == "case1.psych"


def test_duplicate_tag_raises(ts):
    ts.create_tag("hansen.psych", owner_set="hansen-case")
    with pytest.raises(ValueError):
        ts.create_tag("hansen.psych", owner_set="hansen-case")


def test_add_items(ts):
    ts.create_tag("case.tag", owner_set="case")
    items = [
        TagItem(set_slug="case", doc_uuid="uuid-1"),
        TagItem(set_slug="laws", doc_uuid="uuid-2", chunks=[0, 1]),
    ]
    ts.add_items("case.tag", items)
    tag = ts.get_tag("case.tag")
    assert len(tag.items) == 2
    assert tag.items[1].chunks == [0, 1]


def test_add_items_deduplicates(ts):
    ts.create_tag("case.tag", owner_set="case")
    item = TagItem(set_slug="case", doc_uuid="uuid-1")
    ts.add_items("case.tag", [item])
    ts.add_items("case.tag", [item])  # duplicate
    tag = ts.get_tag("case.tag")
    assert len(tag.items) == 1


def test_remove_item(ts):
    ts.create_tag("case.tag", owner_set="case")
    ts.add_items("case.tag", [TagItem(set_slug="case", doc_uuid="uuid-1")])
    ts.remove_item("case.tag", "case", "uuid-1")
    tag = ts.get_tag("case.tag")
    assert len(tag.items) == 0


def test_delete_tag(ts):
    ts.create_tag("case.tag", owner_set="case")
    ts.delete_tag("case.tag")
    with pytest.raises(KeyError):
        ts.get_tag("case.tag")


def test_qualify_adds_prefix(ts):
    assert TagService.qualify("psych", "hansen-case") == "hansen-case.psych"
    assert TagService.qualify("hansen-case.psych", "other") == "hansen-case.psych"


def test_persistence_across_instances(tmp_path):
    ts1 = TagService(tmp_path)
    ts1.create_tag("case.tag", owner_set="case")
    ts1.add_items("case.tag", [TagItem(set_slug="case", doc_uuid="uuid-abc")])

    ts2 = TagService(tmp_path)  # new instance, reads from same file
    tag = ts2.get_tag("case.tag")
    assert len(tag.items) == 1
    assert tag.items[0].doc_uuid == "uuid-abc"
