"""Tests for CLI functionality."""

import io
import sys
from contextlib import redirect_stderr, redirect_stdout

from ruamel import yaml


def test_cli_extract(tmp_path):
    input_file = tmp_path / "input.md"
    config_file = tmp_path / "config.yaml"
    input_file.write_text("Hello John Doe and Jon Doe, CPR: 123456-1234")

    old_argv = sys.argv
    sys.argv = ["did", "extract", str(input_file), "--config", str(config_file)]

    from did.cli import main

    with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
        try:
            main()
        except SystemExit as e:
            if e.code != 0:
                raise

    sys.argv = old_argv
    output = out.getvalue()

    assert "PERSON found: 2" in output
    assert config_file.exists()
    yaml_obj = yaml.YAML()
    with open(config_file) as f:
        config = yaml_obj.load(f)
        assert len(config["PERSON"]) >= 1
        assert any(
            "123456-1234" in entry["variants"]
            for entry in config.get("GENERAL_NUMBER", [])
            + config.get("PHONE_NUMBER", [])
        )


def test_cli_anonymize(tmp_path):
    input_file = tmp_path / "input.md"
    config_file = tmp_path / "config.yaml"
    output_file = tmp_path / "output.md"
    original_text = "Hello John Doe and Jon Doe, CPR: 123456-1234"
    input_file.write_text(original_text)

    old_argv = sys.argv
    sys.argv = ["did", "extract", str(input_file), "--config", str(config_file)]
    from did.cli import main

    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            main()
        except SystemExit as e:
            if e.code != 0:
                raise
    sys.argv = old_argv

    modified_text = (
        original_text
        + " and John Doe again, and new person Alice, new CPR: 987654-4321"
    )
    input_file.write_text(modified_text)

    sys.argv = [
        "did",
        "pseudo",
        "plain",
        str(input_file),
        "--config",
        str(config_file),
        "--output",
        str(output_file),
    ]
    with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
        try:
            main()
        except SystemExit as e:
            if e.code != 0:
                raise
    sys.argv = old_argv
    output = out.getvalue()

    assert "PERSON replaced: 3" in output
    assert output_file.exists()
    with open(output_file) as f:
        content = f.read()
        assert "#(P1V" in content
        assert "Alice" in content
        assert "987654-4321" in content
        assert content.count("#(P1V") == 3
