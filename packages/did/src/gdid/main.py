"""Main GUI application for DID pseudonymization."""

import io
import multiprocessing
import re
import sys
import tempfile
import zipfile
from pathlib import Path

import fitz
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from ruamel import yaml

from did.core.anonymizer import Anonymizer
from did.utils.file_utils import export_to_typst, extract_text


def extract_text_worker(f):
    """Worker function for multiprocessing text extraction."""
    try:
        if f.suffix.lower() == ".pdf":
            doc = fitz.open(str(f))
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
        else:
            text = extract_text(f)
        return f, text
    except Exception:
        return f, None


class SaveDialog(QDialog):
    """Dialog for selecting save options."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Save Options")
        layout = QVBoxLayout(self)
        self.single_radio = QRadioButton("Single (all as chapters in Typst)")
        self.multi_radio = QRadioButton("Multi (separate files)")
        self.multi_radio.setChecked(True)
        layout.addWidget(self.single_radio)
        layout.addWidget(self.multi_radio)
        btn = QPushButton("OK")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)

    def get_option(self):
        return "single" if self.single_radio.isChecked() else "multi"


class MainWindow(QMainWindow):
    """Main window for the DID GUI."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DID Pseudonymization GUI")
        self.language = "da"
        self.files = []
        self.extracted_texts = {}
        self.anonymized_texts = {}
        self.yaml_configs = {}
        self.anonymizer = None
        self.temp_dirs = []  # To clean up
        self.init_ui()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_splitter = QSplitter(Qt.Horizontal)

        # Left pane
        left_widget = QWidget()
        left_widget.setMinimumWidth(160)
        left_widget.setMaximumWidth(220)
        left_layout = QVBoxLayout(left_widget)
        left_layout.addWidget(QLabel("<b>Files</b>"))
        self.load_btn = QPushButton("Load")
        self.load_btn.clicked.connect(self.load_files)
        left_layout.addWidget(self.load_btn)
        left_layout.addWidget(QLabel("Language:"))
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["en", "da"])
        self.lang_combo.setCurrentText("da")
        self.lang_combo.currentTextChanged.connect(self.change_language)
        left_layout.addWidget(self.lang_combo)
        left_layout.addWidget(QLabel("<b>Pipeline</b>"))
        self.parse_btn = QPushButton("Extract Text")
        self.parse_btn.clicked.connect(self.extract_texts)
        left_layout.addWidget(self.parse_btn)
        self.detect_btn = QPushButton("Detect Entities")
        self.detect_btn.clicked.connect(self.detect_entities)
        left_layout.addWidget(self.detect_btn)
        self.pseudo_btn = QPushButton("Pseudonymize")
        self.pseudo_btn.clicked.connect(self.pseudonymize)
        left_layout.addWidget(self.pseudo_btn)
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save_files)
        left_layout.addWidget(self.save_btn)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        left_layout.addWidget(self.progress_bar)
        left_layout.addStretch()
        main_splitter.addWidget(left_widget)

        # Mid pane — file list (top) + YAML editor (bottom)
        mid_widget = QWidget()
        mid_layout = QVBoxLayout(mid_widget)
        mid_splitter = QSplitter(Qt.Vertical)

        file_list_widget = QWidget()
        file_list_layout = QVBoxLayout(file_list_widget)
        file_list_layout.setContentsMargins(0, 0, 0, 0)
        file_list_layout.addWidget(QLabel("<b>Files</b>"))
        self.file_list = QListWidget()
        self.file_list.itemSelectionChanged.connect(self.show_file_content)
        file_list_layout.addWidget(self.file_list)

        yaml_widget = QWidget()
        yaml_layout = QVBoxLayout(yaml_widget)
        yaml_layout.setContentsMargins(0, 0, 0, 0)
        yaml_layout.addWidget(QLabel("<b>Config (YAML)</b>"))
        self.bottom_text = QTextEdit()
        yaml_layout.addWidget(self.bottom_text)

        mid_splitter.addWidget(file_list_widget)
        mid_splitter.addWidget(yaml_widget)
        mid_splitter.setSizes([300, 300])
        mid_layout.addWidget(mid_splitter)
        main_splitter.addWidget(mid_widget)

        # Right pane — preview
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.addWidget(QLabel("<b>Preview</b>"))
        self.right_text = QTextEdit()
        self.right_text.setReadOnly(True)
        right_layout.addWidget(self.right_text)
        main_splitter.addWidget(right_widget)

        main_splitter.setSizes([180, 320, 600])
        main_layout.addWidget(main_splitter)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_W and event.modifiers() == Qt.ControlModifier:
            self.close()
        else:
            super().keyPressEvent(event)

    def load_files(self):
        # Load PDFs or ZIP
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Files", "", "PDF files (*.pdf);;ZIP files (*.zip)"
        )
        if not files:
            return
        self.files = []
        for f in files:
            path = Path(f)
            if path.suffix == ".zip":
                temp_dir = Path(tempfile.mkdtemp())
                self.temp_dirs.append(temp_dir)
                with zipfile.ZipFile(path, "r") as zip_ref:
                    zip_ref.extractall(temp_dir)
                self.files.extend(list(temp_dir.glob("*.pdf")))
            elif path.suffix == ".pdf":
                self.files.append(path)
        # Reset processing data for new files
        self.extracted_texts = {}
        self.yaml_configs = {}
        self.anonymized_texts = {}
        self.anonymizer = None
        self.update_file_list()
        if self.file_list.count() > 0:
            self.file_list.setCurrentRow(0)

    def update_file_list(self):
        self.file_list.clear()
        for f in self.files:
            parsed = f in self.extracted_texts
            detected = f in self.yaml_configs
            pseudonymized = f in self.anonymized_texts
            parsed_color = "green" if parsed else "red"
            detected_color = "green" if detected else "red"
            pseudo_color = "green" if pseudonymized else "red"
            text = f'<span style="color: {parsed_color};">parse</span> <span style="color: {detected_color};">detect</span> <span style="color: {pseudo_color};">pseudo</span> {f.name}'
            item = QListWidgetItem()
            item.setData(Qt.UserRole, f)
            label = QLabel(text)
            label.setTextFormat(Qt.RichText)
            self.file_list.addItem(item)
            self.file_list.setItemWidget(item, label)

    def change_language(self, lang):
        self.language = lang

    def extract_texts(self):
        if not self.files:
            QMessageBox.warning(self, "Warning", "No files loaded.")
            return
        with multiprocessing.Pool() as pool:
            results = pool.map(extract_text_worker, self.files)

        for f, text in results:
            if text is None:
                QMessageBox.warning(self, "Error", f"Failed to extract text from {f}")
            else:
                self.extracted_texts[f] = text
        self.update_file_list()

    def detect_entities(self):
        if not self.extracted_texts:
            QMessageBox.warning(self, "Warning", "Extract texts first.")
            return
        self.anonymizer = Anonymizer(language=self.language)
        all_texts = list(self.extracted_texts.values())
        self.anonymizer.detect_entities(all_texts)
        yaml_config = self.anonymizer.generate_yaml()
        for f in self.files:
            self.yaml_configs[f] = yaml_config
        self.update_file_list()
        self.update_bottom_text()

    def update_bottom_text(self):
        current = self.file_list.currentItem()
        if current:
            f = current.data(Qt.UserRole)
            if f in self.yaml_configs:
                self.bottom_text.setText(self.yaml_configs[f])
        # No selection, set to first available
        elif self.yaml_configs:
            self.bottom_text.setText(next(iter(self.yaml_configs.values())))

    def pseudonymize(self):
        if not self.anonymizer or not self.yaml_configs:
            QMessageBox.warning(self, "Warning", "Detect entities first.")
            return
        yaml_obj = yaml.YAML()
        yaml_text = self.bottom_text.toPlainText()
        try:
            config_data = yaml_obj.load(io.StringIO(yaml_text))
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Invalid YAML: {e}")
            return
        if config_data is None:
            QMessageBox.warning(self, "Error", "YAML is empty or invalid.")
            return
        self.anonymizer.load_replacements(config_data)
        for f in self.files:
            if f in self.extracted_texts:
                text = self.extracted_texts[f]
                anonymized, _ = self.anonymizer.anonymize(text)
                self.anonymized_texts[f] = anonymized
        # Update yaml_configs with the modified YAML
        for f in self.files:
            self.yaml_configs[f] = yaml_text
        self.update_file_list()
        if self.file_list.count() > 0:
            self.file_list.setCurrentRow(0)

    def show_file_content(self):
        current = self.file_list.currentItem()
        if current:
            f = current.data(Qt.UserRole)
            self.update_bottom_text()
            if f in self.anonymized_texts:
                # Generate Typst content
                temp_file = Path(tempfile.mktemp(suffix=".typ"))
                try:
                    export_to_typst(f, self.anonymizer, temp_file)
                    with open(temp_file, encoding="utf-8") as tf:
                        content = tf.read()
                    # Highlight replacements in green
                    highlighted_content = re.sub(
                        r"(<[^>]+>)", r'<span style="color: green;">\1</span>', content
                    )
                    # Color variables
                    highlighted_content = re.sub(
                        r"(#P\d+)",
                        r'<span style="color: green;">\1</span>',
                        highlighted_content,
                    )
                    highlighted_content = re.sub(
                        r"(#G\d+)",
                        r'<span style="color: red;">\1</span>',
                        highlighted_content,
                    )
                    highlighted_content = re.sub(
                        r"(#A\d+)",
                        r'<span style="color: yellow;">\1</span>',
                        highlighted_content,
                    )
                    highlighted_content = re.sub(
                        r"(#E\d+)",
                        r'<span style="color: cyan;">\1</span>',
                        highlighted_content,
                    )
                    # Color all Typst variable tags yellow
                    highlighted_content = re.sub(
                        r"(#\([^)]+\))",
                        r'<span style="color: yellow;">\1</span>',
                        highlighted_content,
                    )
                    # Preserve formatting with <pre>
                    html_content = f"<pre>{highlighted_content}</pre>"
                    self.right_text.setHtml(html_content)
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to generate Typst: {e}")
                finally:
                    if temp_file.exists():
                        temp_file.unlink()

    def save_files(self):
        if not self.anonymized_texts:
            QMessageBox.warning(self, "Warning", "Pseudonymize first.")
            return
        dialog = SaveDialog()
        if dialog.exec():
            option = dialog.get_option()
            out_dir = QFileDialog.getExistingDirectory(self, "Select Output Directory")
            if out_dir:
                out_path = Path(out_dir)
                if option == "multi":
                    sub_dir = out_path / "pseudonymized"
                    sub_dir.mkdir(exist_ok=True)
                    # Write YAML config
                    yaml_file = sub_dir / "config.yaml"
                    with open(yaml_file, "w", encoding="utf-8") as yf:
                        yf.write(self.yaml_configs[next(iter(self.yaml_configs))])
                    # Shared vars files
                    vars_filename = sub_dir / "shared_vars.typ"
                    fakevars_filename = sub_dir / "shared_fakevars.typ"
                    self.progress_bar.setVisible(True)
                    self.progress_bar.setRange(0, len(self.files))
                    progress = 0
                    for f in self.files:
                        if f in self.anonymized_texts:
                            out_file = sub_dir / f"{f.stem}_pseudonymized.typ"
                            try:
                                export_to_typst(
                                    f,
                                    self.anonymizer,
                                    out_file,
                                    vars_filename=str(vars_filename),
                                    fakevars_filename=str(fakevars_filename),
                                )
                            except Exception as e:
                                QMessageBox.warning(
                                    self, "Error", f"Failed to save {f}: {e}"
                                )
                        progress += 1
                        self.progress_bar.setValue(progress)
                    self.progress_bar.setVisible(False)
                else:
                    # Single save
                    sub_dir = out_path / "single_pseudonymized"
                    sub_dir.mkdir(exist_ok=True)
                    # Shared vars files
                    vars_filename = sub_dir / "shared_vars.typ"
                    fakevars_filename = sub_dir / "shared_fakevars.typ"
                    out_file = sub_dir / "combined.typ"
                    with open(out_file, "w", encoding="utf-8") as out_f:
                        out_f.write('#import "shared_vars.typ": *\n#outline()\n\n')
                        for f in self.files:
                            if f in self.anonymized_texts:
                                temp_file = Path(tempfile.mktemp(suffix=".typ"))
                                try:
                                    export_to_typst(
                                        f,
                                        self.anonymizer,
                                        temp_file,
                                        vars_filename=str(vars_filename),
                                        fakevars_filename=str(fakevars_filename),
                                    )
                                    with open(temp_file, encoding="utf-8") as tf:
                                        content = tf.read()
                                    # Remove import lines
                                    lines = content.split("\n")
                                    filtered_lines = [
                                        line
                                        for line in lines
                                        if not line.startswith("#import")
                                    ]
                                    body = "\n".join(filtered_lines).strip()
                                    out_f.write(f"= {f.name}\n\n{body}\n\n")
                                except Exception as e:
                                    QMessageBox.warning(
                                        self, "Error", f"Failed to process {f}: {e}"
                                    )
                                finally:
                                    if temp_file.exists():
                                        temp_file.unlink()
                    # Write YAML config
                    yaml_file = sub_dir / "config.yaml"
                    with open(yaml_file, "w", encoding="utf-8") as yf:
                        yf.write(self.yaml_configs[next(iter(self.yaml_configs))])

    def closeEvent(self, event):
        # Clean up temp dirs
        for d in self.temp_dirs:
            import shutil

            shutil.rmtree(d, ignore_errors=True)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
