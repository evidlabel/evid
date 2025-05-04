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
)
from PyQt6.QtCore import Qt
from pathlib import Path
import yaml
import subprocess
import logging
from evid.core.label_setup import textpdf_to_latex, csv_to_bib
from evid.core.rebut_doc import rebut_doc
import arrow

# Set up logging with detailed output
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class BrowseEvidenceTab(QWidget):
    def __init__(self, directory: Path):
        super().__init__()
        self.directory = directory
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Dataset selection
        dataset_layout = QHBoxLayout()
        dataset_layout.addWidget(QLabel("Dataset:"))
        self.dataset_combo = QComboBox()
        self.dataset_combo.addItems(self.get_datasets())
        if self.dataset_combo.count() > 0:
            self.dataset_combo.setCurrentIndex(0)
        dataset_layout.addWidget(self.dataset_combo)
        dataset_layout.addWidget(QPushButton("Load", clicked=self.load_metadata))
        dataset_layout.addWidget(QPushButton("Open Dir", clicked=self.open_directory))
        layout.addLayout(dataset_layout)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Author", "Title", "Date", "File Name", "UUID"]
        )
        self.table.setSortingEnabled(True)  # Enable sorting
        self.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)  # Default sort by Date (latest first)

        # Set default column widths
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)  # Allow manual resizing
        self.table.setColumnWidth(0, 200)  # Author: wider default
        self.table.setColumnWidth(1, 250)  # Title: wider default
        self.table.setColumnWidth(2, 100)  # Date
        self.table.setColumnWidth(3, 150)  # File Name
        self.table.setColumnWidth(4, 150)  # UUID

        # Make columns stretch when window resizes
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Author stretches
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Title stretches
        layout.addWidget(self.table)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addWidget(QPushButton("Label", clicked=self.create_label))
        button_layout.addWidget(QPushButton("Rebut", clicked=self.run_rebut))
        layout.addLayout(button_layout)

        self.setLayout(layout)

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
            QMessageBox.warning(self, "No Dataset", "Please select a dataset to load.")
            return

        # Fully reset table
        self.table.setSortingEnabled(False)  # Disable sorting during population
        self.table.clearContents()
        self.table.setRowCount(0)
        logger.debug(f"Loading metadata for dataset: {dataset}")

        entries = []
        for info_file in self.directory.glob(f"{dataset}/**/info.yml"):
            try:
                # Read raw content for debugging
                with info_file.open("r", encoding="utf-8") as f:
                    raw_content = f.read()
                    logger.debug(f"Raw YAML for {info_file}: {raw_content}")

                # Parse YAML
                with info_file.open("r", encoding="utf-8") as f:
                    metadata = yaml.safe_load(f)

                # Validate metadata
                if metadata is None:
                    logger.warning(f"Skipping {info_file}: Empty or malformed YAML")
                    continue
                if not isinstance(metadata, dict):
                    logger.warning(f"Skipping {info_file}: Expected dict, got {type(metadata).__name__}")
                    continue

                # Log parsed metadata
                logger.debug(f"Parsed metadata for {info_file}: {metadata}")

                # Check for uuid presence
                if "uuid" not in metadata:
                    logger.warning(f"Skipping {info_file}: Missing UUID field")
                    continue

                # Parse date for sorting
                date_str = str(metadata.get("time_added", "1970-01-01"))
                try:
                    date = arrow.get(date_str, "YYYY-MM-DD")
                except arrow.parser.ParserError:
                    date = arrow.get("1970-01-01")  # Fallback for invalid dates

                entries.append((date, metadata))
            except yaml.YAMLError as e:
                logger.error(f"YAML parsing error in {info_file}: {str(e)}")
                continue
            except Exception as e:
                logger.error(f"Failed to load {info_file}: {str(e)}")
                continue

        # Sort entries by date (latest first)
        entries.sort(key=lambda x: x[0], reverse=True)
        logger.debug(f"Found {len(entries)} valid entries")

        # Populate table
        for _, metadata in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Set table items with fallbacks
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

            logger.debug(f"Added row {row}: Authors={authors}, Label={label}, UUID={uuid_value}")

        # Re-enable sorting after population
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)

    def open_directory(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select an evidence entry.")
            return

        dataset = self.dataset_combo.currentText()
        uuid_item = self.table.item(row, 4)
        if not uuid_item or not uuid_item.text() or uuid_item.text() == "Unknown":
            QMessageBox.critical(self, "Invalid Entry", "Selected entry has no valid UUID.")
            return

        uuid = uuid_item.text()
        path = self.directory / dataset / uuid
        if not path.exists():
            QMessageBox.critical(self, "Directory Missing", f"The directory {path} does not exist.")
            return

        try:
            subprocess.run(["xdg-open", str(path)])
        except subprocess.SubprocessError as e:
            QMessageBox.critical(self, "Error Opening Directory", f"Failed to open directory: {str(e)}")

    def create_label(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select an evidence entry.")
            return

        dataset = self.dataset_combo.currentText()
        uuid_item = self.table.item(row, 4)
        if not uuid_item or not uuid_item.text() or uuid_item.text() == "Unknown":
            QMessageBox.critical(self, "Invalid Entry", "Selected entry has no valid UUID.")
            return

        uuid = uuid_item.text()
        file_name = self.table.item(row, 3).text()
        file_path = self.directory / dataset / uuid / file_name
        label_file = file_path.parent / "label.tex"
        csv_file = file_path.parent / "label.csv"
        bib_file = file_path.parent / "label_table.bib"

        try:
            if not label_file.exists():
                textpdf_to_latex(file_path, label_file)

            # Open the labeller and wait for it to close
            subprocess.run(["xdg-open", str(label_file)], check=True)

            # After labeller closes, check for CSV and generate BibTeX
            if csv_file.exists():
                csv_to_bib(csv_file, bib_file, exclude_note=True)
                logger.info(f"Generated BibTeX file: {bib_file}")
            else:
                logger.warning(f"CSV file {csv_file} not found after labelling")
                QMessageBox.warning(
                    self,
                    "CSV Missing",
                    f"No label.csv found in {file_path.parent}. BibTeX generation skipped."
                )
        except subprocess.SubprocessError as e:
            logger.error(f"Error opening labeller: {str(e)}")
            QMessageBox.critical(
                self, "Error Opening Labeller", f"Failed to open labeller: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error during label workflow: {str(e)}")
            QMessageBox.critical(
                self, "Label Workflow Error", f"An unexpected error occurred: {str(e)}"
            )

    def run_rebut(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(
                self, "No Selection", "Please select an evidence entry to rebut."
            )
            return

        dataset = self.dataset_combo.currentText()
        uuid_item = self.table.item(row, 4)
        if not uuid_item or not uuid_item.text() or uuid_item.text() == "Unknown":
            QMessageBox.critical(self, "Invalid Entry", "Selected entry has no valid UUID.")
            return

        uuid = uuid_item.text()
        workdir = self.directory / dataset / uuid

        if not workdir.exists():
            logger.warning(f"Working directory {workdir} does not exist for rebuttal")
            QMessageBox.critical(
                self,
                "Directory Missing",
                f"The evidence directory {workdir} does not exist. It may have been moved or deleted.",
            )
            return

        try:
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
