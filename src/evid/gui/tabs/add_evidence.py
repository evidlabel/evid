from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QTextEdit,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from pathlib import Path
import uuid
import arrow
import yaml
import shutil
import subprocess
from evid.core.dateextract import extract_dates_from_pdf
import requests
from io import BytesIO
import PyPDF2


class AddEvidenceTab(QWidget):
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
        from PyQt6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select PDF", str(Path.home() / "Downloads"), "PDF Files (*.pdf)"
        )
        if file_path:
            self.file_input.setText(file_path)
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
                self, "Error Opening File", f"Failed to open PDF: {str(e)}"
            )

    def _extract_pdf_date(self, meta):
        """Extracts and formats the date from PDF metadata."""
        date = meta.get("/CreationDate") or meta.get("/ModDate")
        if date and date.startswith("D:"):
            # Format: D:YYYYMMDDHHmmSS
            date = date[2:10]  # YYYYMMDD
            date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        else:
            date = ""
        return date

    def _extract_pdf_authors(self, meta):
        """Extracts the author(s) from PDF metadata."""
        author = meta.get("/Author")
        if author:
            return author
        return ""

    def prefill_fields(self, file_path: Path):
        title = file_path.stem
        try:
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                meta = reader.metadata
                date = self._extract_pdf_date(meta)
                authors = self._extract_pdf_authors(meta)
        except Exception:
            date = ""
            authors = ""
        self.title_input.setText(title)
        self.authors_input.setText(authors)
        self.tags_input.setText("")
        self.dates_input.setText(date)
        self.label_input.setText(title.replace(" ", "_").lower())
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
            (self.directory / dataset_name).mkdir(parents=True, exist_ok=True)
            self.dataset_combo.addItem(dataset_name)
            self.dataset_combo.setCurrentText(dataset_name)

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

        unique_dir = self.directory / dataset / str(uuid.uuid4())
        unique_dir.mkdir(parents=True)

        file_path = Path(self.file_input.text())
        file_name = (
            self.memory_file_name
            if hasattr(self, "memory_file_name")
            else file_path.name
        )

        info = {
            "original_name": file_name,
            "uuid": unique_dir.name,
            "time_added": arrow.now().format("YYYY-MM-DD"),
            "dates": self.dates_input.text(),
            "title": self.title_input.text(),
            "authors": self.authors_input.text(),
            "tags": self.tags_input.text(),
            "label": self.label_input.text(),
            "url": self.url_input.text(),
        }

        target_path = unique_dir / file_name
        if hasattr(self, "memory_pdf_file") and self.memory_pdf_file:
            with target_path.open("wb") as f:
                f.write(self.memory_pdf_file.getvalue())
            del self.memory_pdf_file
            del self.memory_file_name
        else:
            shutil.copy2(file_path, target_path)

        with (unique_dir / "info.yml").open("w") as f:
            yaml.dump(info, f)

        print(f"Added evidence to {unique_dir}")

    def quick_add_from_url(self):
        url = self.url_input.text()
        if not url:
            QMessageBox.warning(self, "No URL", "Please enter a URL to add.")
            return

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            file_name = url.split("/")[-1] or "document.pdf"

            if "application/pdf" not in content_type:
                QMessageBox.warning(
                    self, "Invalid File", "URL must point to a PDF file."
                )
                return

            pdf_file = BytesIO(response.content)
            self.prefill_fields_from_url(pdf_file, file_name)
            self.memory_pdf_file = pdf_file
            self.memory_file_name = file_name
        except requests.RequestException as e:
            QMessageBox.critical(self, "URL Error", f"Failed to download PDF: {str(e)}")

    def prefill_fields_from_url(self, pdf_file: BytesIO, file_name: str):
        self.file_input.setText(file_name)
        title = Path(file_name).stem
        try:
            pdf_file.seek(0)
            reader = PyPDF2.PdfReader(pdf_file)
            meta = reader.metadata
            date = self._extract_pdf_date(meta)
            authors = self._extract_pdf_authors(meta)
        except Exception:
            date = ""
            authors = ""
        self.title_input.setText(title)
        self.authors_input.setText(authors)
        self.tags_input.setText("")
        self.dates_input.setText(date)
        self.label_input.setText(title.replace(" ", "_").lower())
        self.update_preview()
