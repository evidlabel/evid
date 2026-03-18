"""GUI tab for browsing evidence."""

import logging
import subprocess
from pathlib import Path

import arrow
import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from evid import DEFAULT_DIR
from evid.core.bibtex import generate_bib_from_typ
from evid.core.label import create_label
from evid.core.models import InfoModel
from evid.core.prompt import create_prompt

logger = logging.getLogger(__name__)


class BrowseEvidenceTab(QWidget):
    """Tab for browsing and managing existing evidence."""

    def __init__(self, directory: Path = DEFAULT_DIR):
        super().__init__()
        self.directory = directory
        self.metadata_entries = []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Dataset selection
        dataset_layout = QHBoxLayout()
        dataset_layout.addWidget(QLabel("Dataset:"))
        self.dataset_combo = QComboBox()
        self.dataset_combo.addItems(self.get_datasets())
        self.dataset_combo.currentIndexChanged.connect(self.load_metadata)
        dataset_layout.addWidget(self.dataset_combo)
        dataset_layout.addWidget(QPushButton("Reload", clicked=self.load_metadata))
        dataset_layout.addWidget(QPushButton("Open Dir", clicked=self.open_directory))
        layout.addLayout(dataset_layout)

        # Search field
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search metadata...")
        self.search_input.textChanged.connect(self.filter_metadata)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # Table: Y=info.yml valid, F=file present, J=label.json present, then metadata
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Y", "F", "J", "Author", "Title", "Date", "File Name", "UUID"]
        )
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(5, Qt.SortOrder.DescendingOrder)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 24)
        self.table.setColumnWidth(1, 24)
        self.table.setColumnWidth(2, 24)
        self.table.setColumnWidth(3, 200)
        self.table.setColumnWidth(4, 250)
        self.table.setColumnWidth(5, 100)
        self.table.setColumnWidth(6, 150)
        self.table.setColumnWidth(7, 150)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(True)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addWidget(
            QPushButton("Label Selected", clicked=self.create_labels)
        )
        button_layout.addWidget(
            QPushButton("Generate BibTeX", clicked=self.generate_bibtex)
        )
        button_layout.addWidget(QPushButton("Rebut", clicked=self.run_rebut))
        button_layout.addWidget(QPushButton("Prompt", clicked=self.create_prompt))
        layout.addLayout(button_layout)

        self.setLayout(layout)

        if self.dataset_combo.count() > 0:
            self.dataset_combo.setCurrentIndex(0)
            self.load_metadata()

    def get_datasets(self):
        return (
            [
                d.name
                for d in self.directory.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            ]
            if self.directory.exists()
            else []
        )

    def load_metadata(self):
        dataset = self.dataset_combo.currentText()
        if not dataset:
            return

        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(0)
        self.metadata_entries = []
        logger.debug("Loading metadata for dataset: %s", dataset)

        for info_file in self.directory.glob(f"{dataset}/**/info.yml"):
            uuid_from_dir = info_file.parent.name
            try:
                with info_file.open("r", encoding="utf-8") as f:
                    metadata = yaml.safe_load(f)

                if (
                    metadata is None
                    or not isinstance(metadata, dict)
                    or "uuid" not in metadata
                ):
                    self.metadata_entries.append((
                        arrow.get("1970-01-01"),
                        {"uuid": uuid_from_dir, "original_name": "", "label": "", "authors": "", "time_added": ""},
                        False,
                    ))
                    continue

                validated_metadata = InfoModel(**metadata)
                metadata = validated_metadata.model_dump()

                date_str = str(metadata.get("time_added", "1970-01-01"))
                try:
                    date = arrow.get(date_str, "YYYY-MM-DD")
                except arrow.parser.ParserError:
                    date = arrow.get("1970-01-01")

                self.metadata_entries.append((date, metadata, True))
            except (ValueError, yaml.YAMLError, Exception) as e:
                logger.error("Failed to load %s: %s", info_file, e)
                self.metadata_entries.append((
                    arrow.get("1970-01-01"),
                    {"uuid": uuid_from_dir, "original_name": "", "label": "", "authors": "", "time_added": ""},
                    False,
                ))

        self.metadata_entries.sort(key=lambda x: x[0], reverse=True)
        logger.debug("Found %d valid entries", len(self.metadata_entries))
        self.filter_metadata()

    def filter_metadata(self):
        search_text = self.search_input.text().strip().lower()
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(0)

        dataset = self.dataset_combo.currentText()
        for date, metadata, yml_ok in self.metadata_entries:
            metadata_str = " ".join(str(value).lower() for value in metadata.values())
            if not search_text or search_text in metadata_str:
                row = self.table.rowCount()
                self.table.insertRow(row)

                authors = str(metadata.get("authors", ""))
                label = str(metadata.get("label", ""))
                time_added = str(metadata.get("time_added", ""))
                original_name = str(metadata.get("original_name", ""))
                uuid_value = str(metadata.get("uuid", ""))

                entry_dir = self.directory / dataset / uuid_value
                file_ok = bool(original_name) and (entry_dir / original_name).exists()
                json_ok = (entry_dir / "label.json").exists()

                for col, ok in enumerate([yml_ok, file_ok, json_ok]):
                    item = QTableWidgetItem("✓" if ok else "✗")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(row, col, item)

                self.table.setItem(row, 3, QTableWidgetItem(authors))
                self.table.setItem(row, 4, QTableWidgetItem(label))
                self.table.setItem(row, 5, QTableWidgetItem(time_added))
                self.table.setItem(row, 6, QTableWidgetItem(original_name))
                self.table.setItem(row, 7, QTableWidgetItem(uuid_value))

        self.table.setSortingEnabled(True)
        self.table.sortByColumn(5, Qt.SortOrder.DescendingOrder)

    def open_directory(self):
        """Open selected directories in a single VS Code window."""
        selected_rows = sorted(
            set(index.row() for index in self.table.selectedIndexes())
        )
        if not selected_rows:
            logger.warning("No selection — please select at least one entry.")
            return

        dataset = self.dataset_combo.currentText()
        paths = []
        for row in selected_rows:
            uuid_item = self.table.item(row, 7)
            if not uuid_item or not uuid_item.text() or uuid_item.text() == "Unknown":
                logger.error("Row %d has no valid UUID.", row + 1)
                continue

            uuid = uuid_item.text()
            path = self.directory / dataset / uuid
            if not path.exists():
                logger.error("Directory missing: %s", path)
                continue
            paths.append(str(path))

        if paths:
            try:
                subprocess.run(["code"] + paths, check=True)
            except subprocess.SubprocessError as e:
                logger.error("Failed to open VS Code: %s", e)

    def create_labels(self):
        selected_rows = sorted(
            set(index.row() for index in self.table.selectedIndexes())
        )
        if not selected_rows:
            logger.warning("No selection — please select at least one entry.")
            return

        dataset = self.dataset_combo.currentText()
        for row in selected_rows:
            uuid_item = self.table.item(row, 7)
            if not uuid_item or not uuid_item.text() or uuid_item.text() == "Unknown":
                logger.error("Row %d has no valid UUID.", row + 1)
                continue

            uuid = uuid_item.text()
            file_name = self.table.item(row, 6).text()
            file_path = self.directory / dataset / uuid / file_name
            create_label(file_path, dataset, uuid)

    def generate_bibtex(self):
        selected_rows = sorted(
            set(index.row() for index in self.table.selectedIndexes())
        )
        if not selected_rows:
            logger.warning("No selection — please select at least one entry.")
            return

        dataset = self.dataset_combo.currentText()
        success_count = 0
        bib_contents = []
        for row in selected_rows:
            uuid_item = self.table.item(row, 7)
            if not uuid_item or not uuid_item.text() or uuid_item.text() == "Unknown":
                logger.error("Row %d has no valid UUID.", row + 1)
                continue

            uuid = uuid_item.text()
            file_name = self.table.item(row, 6).text()
            file_path = self.directory / dataset / uuid / file_name
            typ_file = file_path.parent / "label.typ"
            bib_file = file_path.parent / "label.bib"

            if typ_file.exists():
                success, msg = generate_bib_from_typ(typ_file)
                if success:
                    logger.info("Generated BibTeX: %s", bib_file)
                    success_count += 1
                    try:
                        with bib_file.open("r", encoding="utf-8") as f:
                            bib_contents.append(f.read())
                    except Exception as e:
                        logger.warning("Failed to read %s: %s", bib_file, e)
                else:
                    logger.error("BibTeX generation failed (row %d): %s", row + 1, msg)
            else:
                logger.warning("No label.typ for row %d — skipping BibTeX.", row + 1)

        if success_count > 0:
            from PySide6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText("\n\n".join(bib_contents))
            logger.info("BibTeX copied to clipboard (%d entries).", success_count)

    def run_rebut(self):
        selected_rows = sorted(
            set(index.row() for index in self.table.selectedIndexes())
        )
        if not selected_rows:
            logger.warning("No selection — please select an entry to rebut.")
            return

        dataset = self.dataset_combo.currentText()
        for row in selected_rows:
            uuid_item = self.table.item(row, 7)
            if not uuid_item or not uuid_item.text() or uuid_item.text() == "Unknown":
                logger.error("Selected entry has no valid UUID.")
                continue

            uuid = uuid_item.text()
            workdir = self.directory / dataset / uuid

            if not workdir.exists():
                logger.error("Directory missing: %s", workdir)
                continue

            try:
                from evid.core.rebut_doc import rebut_doc
                rebut_doc(workdir)
            except FileNotFoundError as e:
                logger.error("Rebuttal failed: %s", e)
            except Exception as e:
                logger.error("Rebuttal error: %s", e)

    def create_prompt(self):
        """Generate a concatenated Markdown prompt from selected evidence labels."""
        selected_rows = sorted(
            set(index.row() for index in self.table.selectedIndexes())
        )
        uuids = []
        for row in selected_rows:
            uuid_item = self.table.item(row, 7)
            if uuid_item and uuid_item.text() and uuid_item.text() != "Unknown":
                uuids.append(uuid_item.text())
        dataset = self.dataset_combo.currentText()
        create_prompt(uuids, dataset, self.directory)
