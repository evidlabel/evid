import pytest
from evid import load_config, CONFIG, DEFAULT_DIR

from pathlib import Path
import yaml


@pytest.fixture
def mock_config(tmp_path):
    config_path = Path.home() / ".evidrc"
    original_config = config_path.read_text() if config_path.exists() else None
    yield config_path
    if original_config is None:
        config_path.unlink(missing_ok=True)
    else:
        config_path.write_text(original_config)


def test_load_config_defaults():
    config = load_config()
    assert config == {
        "default_dir": str(Path("~/Documents/evid").expanduser()),
        "editor": "code",
        "directory": "code",
        "latex": "pdflatex {file}",
    }


def test_load_config_with_file(mock_config):
    mock_config.write_text(yaml.dump({"editor": "vim"}))
    config = load_config()
    assert config["editor"] == "vim"
    assert "default_dir" in config


def test_load_config_invalid_yaml(mock_config):
    mock_config.write_text("invalid: yaml: here")
    config = load_config()
    assert config == {
        "default_dir": str(Path("~/Documents/evid").expanduser()),
        "editor": "code",
        "directory": "code",
        "latex": "pdflatex {file}",
    }


def test_load_config_validation_error(mock_config):
    mock_config.write_text(yaml.dump({"editor": 123}))
    config = load_config()
    assert config == {
        "default_dir": str(Path("~/Documents/evid").expanduser()),
        "editor": "code",
        "directory": "code",
        "latex": "pdflatex {file}",
    }


def test_config_and_default_dir():
    assert isinstance(CONFIG, dict)
    assert isinstance(DEFAULT_DIR, Path)
