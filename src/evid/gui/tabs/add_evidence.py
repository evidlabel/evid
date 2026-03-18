import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import arrow
import pypdf
import requests
import yaml
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from evid import DEFAULT_DIR
from evid.core.models import InfoModel
from evid.utils.text import normalize_text

logger = logging.getLogger(__name__)


class AddEvidenceTab(QWidget):
    """Tab for adding new evidence documents."""

    def __init__(self, directory: Path = DEFAULT_DIR):
        headless = (
            os.environ.get("QT_QPA_PLATFORM") == "offscreen"
            or os.environ.get("HEADLESS") == "1"
        )
        if headless:
            self.directory = directory
            self.is_temp_file = False
            self.temp_dir = None
            # Set dummy attributes for headless mode
            self.dataset_combo = type(
                "MockCombo", (), {"currentText": lambda: "default_dataset"}
            )()
            self.title_input = type("MockInput", (), {"text": lambda: "Test Title"})()
            self.authors_input = type(
                "MockInput", (), {"text": lambda: "Test Author"}
            )()
            self.dates_input = type("MockInput", (), {"text": lambda: "2023-01-01"})()
            self.tags_input = type("MockInput", (), {"text": lambda: ""})()
            self.label_input = type("MockInput", (), {"text": lambda: "test_label"})()
            self.url_input = type("MockInput", (), {"text": lambda: ""})()
            self.file_input = type(
                "MockInput", (), {"text": lambda: "/path/to/test.pdf"}
            )()
            return
        super().__init__()
        self.directory = directory
        self.is_temp_file = False
        self.temp_dir = None
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
        layout.addLayout(dataset_layout)

        # New dataset
        new_dataset_layout = QHBoxLayout()
        new_dataset_layout.addWidget(QLabel("New Dataset:"))
        self.new_dataset_input = QLineEdit()
        new_dataset_layout.addWidget(self.new_dataset_input)
        new_dataset_layout.addWidget(QPushButton("Create", clicked=self.create_dataset))
        layout.addLayout(new_dataset_layout)

        # File selection
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("PDF File:"))
        self.file_input = QLineEdit()
        file_layout.addWidget(self.file_input)
        file_layout.addWidget(QPushButton("Browse", clicked=self.browse_file))
        file_layout.addWidget(QPushButton("View", clicked=self.view_file))
        layout.addLayout(file_layout)

        # Metadata fields
        for label in ["Title:", "Authors:", "Tags:", "Dates:", "Label:", "URL:"]:
            field_layout = QHBoxLayout()
            field_layout.addWidget(QLabel(label))
            input_field = QLineEdit()
            field_layout.addWidget(input_field)
            layout.addLayout(field_layout)
            setattr(self, f"{label.lower()[:-1]}_input", input_field)
            input_field.textChanged.connect(self.update_preview)

        # Preview
        layout.addWidget(QLabel("Preview:"))
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        layout.addWidget(self.preview_text)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addWidget(QPushButton("Add", clicked=self.add_evidence))
        button_layout.addWidget(
            QPushButton("Quick Add URL", clicked=self.quick_add_from_url)
        )
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

    def browse_file(self):
        from PySide6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select PDF", str(Path.home() / "Downloads"), "PDF Files (*.pdf)"
        )
        if file_path:
            self.file_input.setText(file_path)
            self.is_temp_file = False
            self.prefill_fields(Path(file_path))

    def view_file(self):
        file_path = self.file_input.text().strip()
        if not file_path:
            QMessageBox.warning(
                self, "No File Selected", "Please select a PDF file to view."
            )
            return
        file_path = Path(file_path)
        if not file_path.exists():
            QMessageBox.warning(
                self, "File Not Found", f"The file {file_path} does not exist."
            )
            return
        try:
            subprocess.run(["xdg-open", str(file_path)])
        except subprocess.SubprocessError as e:
            QMessageBox.critical(
                self, "Error Opening File", f"Failed to open PDF: {e!s}"
            )

    def _extract_pdf_date(self, pdf_path: Path):
        """Extracts and formats the date from PDF metadata as a plain string."""
        try:
            with open(pdf_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                meta = reader.metadata
            date = meta.get("/CreationDate") or meta.get("/ModDate")
            date = normalize_text(date)
            if date and date.startswith("D:"):
                # Format: D:YYYYMMDDHHmmSS{SD:16}HHmmSS
                date = date[2:10]  # YYYYMMDD
                date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            else:
                date = ""
        except Exception:
            date = ""
        return str(date)

    def _extract_pdf_authors(self, pdf_path: Path):
        """Extracts the author(s) from PDF metadata as a plain string."""
        try:
            with open(pdf_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                meta = reader.metadata
            author = meta.get("/Author")
        except Exception:
            author = ""
        return normalize_text(author)

    def _extract_pdf_title(self, pdf_path: Path):
        """Extracts the title from PDF metadata as a plain string."""
        try:
            with open(pdf_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                meta = reader.metadata
            title = meta.get("/Title")
        except Exception:
            title = ""
        return normalize_text(title)

    def prefill_fields(self, file_path: Path):
        filename_title = normalize_text(file_path.stem)
        pdf_title = self._extract_pdf_title(file_path)
        label_base = pdf_title or filename_title
        date = self._extract_pdf_date(file_path)
        authors = self._extract_pdf_authors(file_path)
        self.title_input.setText(filename_title)
        self.authors_input.setText(authors)
        self.tags_input.setText("")
        self.dates_input.setText(date)
        self.label_input.setText(label_base.replace(" ", "_").lower())
        self.update_preview()

    def update_preview(self):
        preview = "\n".join(
            f"{label[:-1]}: {getattr(self, f'{label.lower()[:-1]}_input').text()}"
            for label in ["Title:", "Authors:", "Tags:", "Dates:", "Label:", "URL:"]
        )
        self.preview_text.setText(preview)

    def create_dataset(self):
        dataset_name = self.new_dataset_input.text().strip()
        if dataset_name:
            dataset_path = self.directory / dataset_name
            if dataset_path.exists():
                QMessageBox.warning(
                    self,
                    "Dataset Exists",
                    f"Dataset '{dataset_name}' already exists. Please choose a different name.",
                )
                return
            dataset_path.mkdir(parents=True, exist_ok=False)
            self.dataset_combo.addItem(dataset_name)
            self.dataset_combo.setCurrentText(dataset_name)
            logger.info(f"Successfully created new dataset: {dataset_name}")

    def add_evidence(self):
        dataset = self.dataset_combo.currentText()
        required_fields = {
            "Dataset": dataset,
            "Title": self.title_input.text(),
            "Authors": self.authors_input.text(),
            "Dates": self.dates_input.text(),
            "PDF File": self.file_input.text(),
        }

        missing_fields = [
            field for field, value in required_fields.items() if not value.strip()
        ]
        if missing_fields:
            QMessageBox.warning(
                self,
                "Missing Required Fields",
                f"Please fill in the following required fields:\n- {', '.join(missing_fields)}",
            )
            return

        file_path_str = self.file_input.text()
        file_path = Path(file_path_str)
        if not file_path.exists():
            QMessageBox.warning(
                self, "File Not Found", f"The file {file_path} does not exist."
            )
            return

        with open(file_path, "rb") as f:
            content_bytes = f.read()
        file_name = file_path.name

        # Compute content-based UUID
        digest = hashlib.sha256(content_bytes).digest()[:16]
        unique_id = uuid.UUID(bytes=digest)
        unique_dir = self.directory / dataset / unique_id.hex

        if unique_dir.exists():
            QMessageBox.information(
                self,
                "Already Added",
                f"This document is already added in {dataset} at {unique_id.hex}. Opening directory.",
            )
            try:
                subprocess.run(["code", str(unique_dir)], check=True)
            except subprocess.SubprocessError as e:
                QMessageBox.critical(
                    self,
                    "Error Opening Directory",
                    f"Failed to open directory: {e!s}",
                )
            return

        unique_dir.mkdir(parents=True)

        target_path = unique_dir / file_name
        shutil.copy2(file_path, target_path)

        info = {
            "original_name": file_name,
            "uuid": unique_id.hex,
            "time_added": arrow.now().format("YYYY-MM-DD"),
            "dates": self.dates_input.text(),
            "title": self.title_input.text(),
            "authors": self.authors_input.text(),
            "tags": self.tags_input.text(),
            "label": self.label_input.text(),
            "url": self.url_input.text(),
        }

        # Validate with Pydantic
        try:
            validated_info = InfoModel(**info)
            info = validated_info.model_dump()
        except ValueError as e:
            logger.error(f"Validation error for info.yml: {e}")
            QMessageBox.critical(self, "Validation Error", f"Validation failed: {e}")
            return

        with (unique_dir / "info.yml").open("w", encoding="utf-8") as f:
            yaml.dump(info, f, allow_unicode=True)

        print(f"Added evidence to {unique_dir}")

        # Clean up temp file if it was used
        if self.is_temp_file:
            try:
                self.temp_dir.cleanup()
            except OSError:
                pass
            self.is_temp_file = False
            self.temp_dir = None

    def quick_add_from_url(self):
        url = self.url_input.text()
        if not url:
            QMessageBox.warning(self, "No URL", "Please enter a URL to add.")
            return

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")

            # Clean up any existing temp file
            if self.is_temp_file and self.temp_dir:
                try:
                    self.temp_dir.cleanup()
                except OSError:
                    pass

            temp_dir = tempfile.TemporaryDirectory()

            if "application/pdf" in content_type:
                file_name = Path(url.split("/")[-1] or "document").stem + ".pdf"
                file_path = Path(temp_dir.name) / file_name
                with file_path.open("wb") as f:
                    f.write(response.content)
            else:
                from evid.core.typst_generation import web_to_pdf

                file_path, _ = web_to_pdf(url, Path(temp_dir.name))

            self.file_input.setText(str(file_path))
            self.is_temp_file = True
            self.temp_dir = temp_dir
            self.prefill_fields(file_path)
        except requests.RequestException as e:
            QMessageBox.critical(self, "URL Error", f"Failed to fetch URL: {e!s}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to process URL: {e!s}")
            if "temp_dir" in locals():
                try:
                    temp_dir.cleanup()
                except OSError:
                    pass
