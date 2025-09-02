import pytest
from unittest.mock import patch
from evid.gui.tabs.add_evidence import AddEvidenceTab


@pytest.fixture
def add_tab(qtbot, tmp_path):
    tab = AddEvidenceTab(tmp_path)
    yield tab


def test_init_ui(add_tab):
    assert add_tab.dataset_combo is not None
    assert add_tab.file_input is not None


def test_create_dataset(add_tab, tmp_path):
    add_tab.new_dataset_input.setText("new_ds")
    add_tab.create_dataset()
    assert "new_ds" in [
        add_tab.dataset_combo.itemText(i) for i in range(add_tab.dataset_combo.count())
    ]


def test_add_evidence(add_tab, tmp_path):
    add_tab.dataset_combo.addItem("test_ds")
    add_tab.dataset_combo.setCurrentText("test_ds")
    (tmp_path / "test_ds").mkdir()
    pdf_path = tmp_path / "test.pdf"
    pdf_path.touch()
    add_tab.file_input.setText(str(pdf_path))
    add_tab.title_input.setText("Title")
    add_tab.authors_input.setText("Author")
    add_tab.dates_input.setText("2023-01-01")
    with patch("shutil.copy2"):
        with patch("yaml.dump"):
            add_tab.add_evidence()
