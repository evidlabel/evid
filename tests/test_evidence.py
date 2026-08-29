"""Tests for CLI evidence listing."""

from evid.cli.evidence import get_evidence_list
from evid.services.set_manager import SetManager


def test_get_evidence_list_skips_dirs_without_info_yml(tmp_path):
    sm = SetManager(tmp_path)
    sm.create_set("Case")
    real = tmp_path / "sets" / "case" / "docs" / "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    real.mkdir(parents=True)
    (real / "info.yml").write_text(
        "uuid: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n"
        "title: PHD_ER_ONLINE\n"
        "original_name: x.pdf\n"
        "time_added: '2024-01-01'\n"
        "dates: '2024'\n"
        "authors: ''\n"
        "tags: ''\n"
        "label: PHD_ER_ONLINE\n"
        "url: ''\n"
    )
    (tmp_path / "sets" / "case" / "docs" / "sets").mkdir()
    rows = get_evidence_list(tmp_path, "case")
    assert [r["uuid"] for r in rows] == ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]
