"""GUI tab for browsing evidence."""

import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QHeaderView,
    QLineEdit,
)
from PyQt6.QtCore import Qt
from pathlib import Path
import yaml
import subprocess
from evid.core.label import create_label
from evid.core.bibtex import generate_bib_from_typ
import arrow
from evid import DEFAULT_DIR
from evid.core.models import InfoModel  # Added for validation

# Set up logging with detailed output
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class BrowseEvidenceTab(QWidget):
    def __init__(self, directory: Path = DEFAULT_DIR):
        super().__init__()
        self.directory = directory
        self.metadata_entries = []  # Store all metadata for filtering
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

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Author", "Title", "Date", "File Name", "UUID"]
        )
        self.table.setSortingEnabled(True)  # Enable sorting
        self.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)  # Default sort by Date
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.ExtendedSelection
        )  # Enable multi-selection

        # Set default column widths
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 200)  # Author
        self.table.setColumnWidth(1, 250)  # Title
        self.table.setColumnWidth(2, 100)  # Date
        self.table.setColumnWidth(3, 150)  # File Name
        self.table.setColumnWidth(4, 150)  # UUID

        # Make columns stretch when window resizes
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Author
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Title
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
        layout.addLayout(button_layout)

        self.setLayout(layout)

        if self.dataset_combo.count() > 0:
            self.dataset_combo.setCurrentIndex(0)
            self.load_metadata()  # Automatically load metadata for the first dataset

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
            return  # Silently return if no dataset selected

        # Fully reset table and metadata
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(0)
        self.metadata_entries = []
        logger.debug(f"Loading metadata for dataset: {dataset}")

        for info_file in self.directory.glob(f"{dataset}/**/info.yml"):
            try:
                with info_file.open("r", encoding="utf-8") as f:
                    metadata = yaml.safe_load(f)

                if (
                    metadata is None
                    or not isinstance(metadata, dict)
                    or "uuid" not in metadata
                ):
                    continue  # Skip invalid entries

                # Validate with Pydantic
                validated_metadata = InfoModel(**metadata)
                metadata = validated_metadata.model_dump()

                date_str = str(metadata.get("time_added", "1970-01-01"))
                try:
                    date = arrow.get(date_str, "YYYY-MM-DD")
                except arrow.parser.ParserError:
                    date = arrow.get("1970-01-01")

                self.metadata_entries.append((date, metadata))
            except ValueError as e:
                logger.error(f"Validation error in {info_file}: {str(e)}")
                continue
            except yaml.YAMLError as e:
                logger.error(f"YAML parsing error in {info_file}: {str(e)}")
                continue
            except Exception as e:
                logger.error(f"Failed to load {info_file}: {str(e)}")
                continue

        # Sort entries by date (latest first)
        self.metadata_entries.sort(key=lambda x: x[0], reverse=True)
        logger.debug(f"Found {len(self.metadata_entries)} valid entries")

        # Populate table with all entries initially
        self.filter_metadata()

    def filter_metadata(self):
        search_text = self.search_input.text().strip().lower()
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(0)

        for date, metadata in self.metadata_entries:
            metadata_str = " ".join(str(value).lower() for value in metadata.values())
            if not search_text or search_text in metadata_str:
                row = self.table.rowCount()
                self.table.insertRow(row)

                authors = str(metadata.get("authors", "Unknown"))
                label = str(metadata.get("label", "Unknown"))
                time_added = str(metadata.get("time_added", "Unknown"))
                original_name = str(metadata.get("original_name", "Unknown"))
                uuid_value = str(metadata.get("uuid", "Unknown"))

                self.table.setItem(row, 0, QTableWidgetItem(authors))
                self.table.setItem(row, 1, QTableWidgetItem(label))
                self.table.setItem(row, 2, QTableWidgetItem(time_added))
                self.table.setItem(row, 3, QTableWidgetItem(original_name))
                self.table.setItem(row, 4, QTableWidgetItem(uuid_value))

                logger.debug(
                    f"Added row {row}: Authors={authors}, Label={label}, UUID={uuid_value}"
                )

        self.table.setSortingEnabled(True)
        self.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)

    def open_directory(self):
        """Open selected directories in a single VS Code window."""
        selected_rows = sorted(
            set(index.row() for index in self.table.selectedIndexes())
        )
        if not selected_rows:
            QMessageBox.warning(
                self, "No Selection", "Please select at least one evidence entry."
            )
            return

        dataset = self.dataset_combo.currentText()
        paths = []
        for row in selected_rows:
            uuid_item = self.table.item(row, 4)
            if not uuid_item or not uuid_item.text() or uuid_item.text() == "Unknown":
                QMessageBox.critical(
                    self, "Invalid Entry", f"Entry in row {row + 1} has no valid UUID."
                )
                continue

            uuid = uuid_item.text()
            path = self.directory / dataset / uuid
            if not path.exists():
                QMessageBox.critical(
                    self, "Directory Missing", f"The directory {path} does not exist."
                )
                continue
            paths.append(str(path))

        if paths:
            try:
                subprocess.run(["code"] + paths, check=True)  # Open all in one window
            except subprocess.SubprocessError as e:
                QMessageBox.critical(
                    self,
                    "Error Opening VS Code",
                    f"Failed to open directories in VS Code: {str(e)}",
                )

    def create_labels(self):
        selected_rows = sorted(
            set(index.row() for index in self.table.selectedIndexes())
        )
        if not selected_rows:
            QMessageBox.warning(
                self, "No Selection", "Please select at least one evidence entry."
            )
            return

        dataset = self.dataset_combo.currentText()
        for row in selected_rows:
            uuid_item = self.table.item(row, 4)
            if not uuid_item or not uuid_item.text() or uuid_item.text() == "Unknown":
                QMessageBox.critical(
                    self, "Invalid Entry", f"Entry in row {row + 1} has no valid UUID."
                )
                continue

            uuid = uuid_item.text()
            file_name = self.table.item(row, 3).text()
            file_path = self.directory / dataset / uuid / file_name

            # Call the shared create_label function
            create_label(file_path, dataset, uuid)

    def generate_bibtex(self):
        selected_rows = sorted(
            set(index.row() for index in self.table.selectedIndexes())
        )
        if not selected_rows:
            QMessageBox.warning(
                self, "No Selection", "Please select at least one evidence entry."
            )
            return

        dataset = self.dataset_combo.currentText()
        success_count = 0
        for row in selected_rows:
            uuid_item = self.table.item(row, 4)
            if not uuid_item or not uuid_item.text() or uuid_item.text() == "Unknown":
                QMessageBox.critical(
                    self, "Invalid Entry", f"Entry in row {row + 1} has no valid UUID."
                )
                continue

            uuid = uuid_item.text()
            file_name = self.table.item(row, 3).text()
            file_path = self.directory / dataset / uuid / file_name
            typ_file = file_path.parent / "label.typ"
            bib_file = file_path.parent / "label.bib"

            if typ_file.exists():
                success, msg = generate_bib_from_typ(typ_file)
                if success:
                    logger.info(f"Generated BibTeX file: {bib_file}")
                    success_count += 1
                else:
                    logger.error(msg)
                    QMessageBox.critical(
                        self,
                        "BibTeX Generation Error",
                        f"Failed to generate BibTeX for row {row + 1}: {msg}",
                    )
            else:
                logger.warning(f"Typst file {typ_file} not found")
                QMessageBox.warning(
                    self,
                    "Typst Missing",
                    f"No label.typ found for entry in row {row + 1}. BibTeX generation skipped.",
                )

        if success_count > 0:
            QMessageBox.information(
                self,
                "BibTeX Generation Complete",
                f"Successfully generated BibTeX files for {success_count} entries.",
            )

    def run_rebut(self):
        selected_rows = sorted(
            set(index.row() for index in self.table.selectedIndexes())
        )
        if not selected_rows:
            QMessageBox.warning(
                self, "No Selection", "Please select an evidence entry to rebut."
            )
            return

        dataset = self.dataset_combo.currentText()
        for row in selected_rows:
            uuid_item = self.table.item(row, 4)
            if not uuid_item or not uuid_item.text() or uuid_item.text() == "Unknown":
                QMessageBox.critical(
                    self, "Invalid Entry", "Selected entry has no valid UUID."
                )
                continue

            uuid = uuid_item.text()
            workdir = self.directory / dataset / uuid

            if not workdir.exists():
                logger.warning(
                    f"Working directory {workdir} does not exist for rebuttal"
                )
                QMessageBox.critical(
                    self,
                    "Directory Missing",
                    f"The evidence directory {workdir} does not exist. It may have been moved or deleted.",
                )
                continue

            try:
                from evid.core.rebut_doc import rebut_doc

                rebut_doc(workdir)
            except FileNotFoundError as e:
                logger.warning(f"Rebuttal failed: {str(e)}")
                QMessageBox.critical(
                    self,
                    "Rebuttal Failed",
                    f"Could not run rebuttal: {str(e)}. Ensure required files are available.",
                )
            except Exception as e:
                logger.warning(f"Unexpected error during rebuttal: {str(e)}")
                QMessageBox.critical(
                    self, "Rebuttal Error", f"An unexpected error occurred: {str(e)}"
                )
