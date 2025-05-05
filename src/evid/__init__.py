import importlib.metadata
from pathlib import Path

NAME = "evid"
try:
    __version__ = importlib.metadata.version(NAME)
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

DEFAULT_DIR = Path("~/Documents/evid").expanduser()
