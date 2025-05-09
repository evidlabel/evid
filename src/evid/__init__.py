import importlib.metadata
from pathlib import Path
import yaml

NAME = "evid"
try:
    __version__ = importlib.metadata.version(NAME)
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

def load_config() -> dict:
    """Load configuration from ~/.evidrc or return default."""
    config_path = Path.home() / ".evidrc"
    default_config = {"default_dir": str(Path("~/Documents/evid").expanduser())}
    if config_path.exists():
        try:
            with config_path.open("r") as f:
                config = yaml.safe_load(f) or {}
                return {**default_config, **config}
        except yaml.YAMLError:
            return default_config
    return default_config

CONFIG = load_config()
DEFAULT_DIR = Path(CONFIG["default_dir"]).expanduser()
