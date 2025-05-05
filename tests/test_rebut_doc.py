import pytest
from pathlib import Path
import subprocess
from unittest.mock import patch
from evid.core.rebut_doc import rebut_doc


@pytest.fixture
def temp_workdir(tmp_path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "label.csv").touch()  # Mock label.csv existence
    yield workdir


@pytest.mark.skip("Skipping test_rebut_doc_success")
@patch("subprocess.run")
def test_rebut_doc_success(mock_run, temp_workdir):
    output_path = Path.home() / "Documents/fct_output"
    rebut_tex = output_path / "rebut.tex"

    # Mock subprocess.run to simulate successful execution
    mock_run.side_effect = [
        subprocess.CompletedProcess(args=["fct_csvbib"], returncode=0),
        subprocess.CompletedProcess(args=["fct_rebut"], returncode=0),
        subprocess.CompletedProcess(args=["xdg-open"], returncode=0),
    ]

    # Mock rebut.tex existence
    with patch("pathlib.Path.exists", return_value=True):
        rebut_doc(temp_workdir)

    assert mock_run.call_count == 3
    mock_run.assert_any_call(
        ["fct_csvbib", "label.csv", "-n"], cwd=temp_workdir, check=True
    )
    mock_run.assert_any_call(
        ["fct_rebut", str(temp_workdir / "label_table.bib")],
        cwd=output_path,
        check=True,
    )
    mock_run.assert_any_call(["xdg-open", str(rebut_tex)])


@pytest.mark.skip("Skipping test_rebut_doc_no_label")
@patch("subprocess.run")
def test_rebut_doc_missing_file(mock_run, temp_workdir):
    mock_run.side_effect = subprocess.CalledProcessError(1, ["fct_csvbib"])

    with pytest.raises(FileNotFoundError) as exc_info:
        rebut_doc(temp_workdir)

    assert "Command failed: ['fct_csvbib'" in str(exc_info.value)
