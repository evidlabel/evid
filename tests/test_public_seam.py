"""Public library seam: types at root, services at evid.services, orphans gone."""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest


def test_database_module_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("evid.core.database")


def test_data_package_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("evid.data")


def test_root_exports_types_and_config():
    import evid
    from evid import (
        ConfigModel,
        Document,
        EvidConfig,
        EvidenceSet,
        InfoModel,
        SetType,
        Tag,
        TagItem,
        VecResult,
        __version__,
    )

    assert evid.__all__ == [
        "ConfigModel",
        "Document",
        "EvidConfig",
        "EvidenceSet",
        "InfoModel",
        "SetType",
        "Tag",
        "TagItem",
        "VecResult",
        "__version__",
    ]
    assert __version__ == "0.5.0"
    assert Document is evid.Document
    assert EvidConfig is evid.EvidConfig
    assert ConfigModel is evid.ConfigModel


def test_services_package_exports_adapters():
    from evid.services import (
        DocIngester,
        SetManager,
        TagService,
        VecService,
        resolve_source,
    )

    assert DocIngester.__name__ == "DocIngester"
    assert SetManager.__name__ == "SetManager"
    assert TagService.__name__ == "TagService"
    assert VecService.__name__ == "VecService"
    assert callable(resolve_source)


def test_import_evid_stays_cheap():
    """Root import must not pull the ingest/embedding stack."""
    code = (
        "import sys, evid\n"
        "assert 'evid.services.doc_ingester' not in sys.modules\n"
        "assert 'evid.vec.embeddings' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_cli_version_is_source_version():
    from evid import __version__
    from evid.cli.main import app

    assert app.version == __version__ == "0.5.0"


def test_cli_db_help_default_is_canonical_path():
    from evid.cli.main import app

    db_opt = next(o for o in app.options if "--db" in o.flags)
    assert db_opt.default == "~/.local/share/evid"
