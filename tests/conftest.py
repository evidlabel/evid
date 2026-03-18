"""Shared pytest fixtures."""

import sys

import pytest


@pytest.fixture(scope="session")
def qapp():
    """Provide a QApplication for Qt widget tests."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    return app
