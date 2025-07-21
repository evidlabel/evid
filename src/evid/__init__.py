from pathlib import Path
import yaml
import importlib.metadata
from evid.core.models import ConfigModel

NAME = "evid"
try:
    __version__ = importlib.metadata.version(NAME)
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"


def load_config() -> dict:
    """Load and validate configuration from ~/.evidrc or return defaults."""
    config_path = Path.home() / ".evidrc"
    if config_path.exists():
        try:
            with config_path.open("r") as f:
                user_config = yaml.safe_load(f) or {}
            config_model = ConfigModel(**user_config)
            return config_model.model_dump()
        except yaml.YAMLError:
            print("Invalid YAML in .evidrc, using defaults.")
            return ConfigModel().model_dump()
        except ValueError as e:  # Includes Pydantic ValidationError
            print(f"Validation error in .evidrc: {e}. Using defaults.")
            return ConfigModel().model_dump()
    else:
        return ConfigModel().model_dump()


CONFIG = load_config()
DEFAULT_DIR = Path(CONFIG["default_dir"]).expanduser()
