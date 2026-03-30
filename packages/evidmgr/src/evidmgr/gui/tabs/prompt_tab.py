"""Prompt Builder tab — recipe-driven evidence assembly."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from evidmgr.gui.signals import AppSignals
    from evidmgr.services.tag_service import TagService

logger = logging.getLogger(__name__)


class PromptTab(QWidget):
    def __init__(
        self,
        tag_service: "TagService",
        signals: "AppSignals",
    ) -> None:
        super().__init__()
        self._tag_service = tag_service
        self._signals = signals
        self._recipe_path: Path | None = None
        self._assembled = None          # AssembledPrompt | None
        self._corpus_index: dict[str, list[str]] = {}

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watcher.directoryChanged.connect(self._on_file_changed)

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._reload)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── left: recipe tree ─────────────────────────────────────────────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        path_row = QHBoxLayout()
        self._path_label = QLabel("No recipe selected")
        self._path_label.setWordWrap(False)
        self._path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._browse_btn = QPushButton("…")
        self._browse_btn.setFixedWidth(30)
        self._browse_btn.clicked.connect(self._on_browse)
        path_row.addWidget(self._path_label, 1)
        path_row.addWidget(self._browse_btn)
        lv.addLayout(path_row)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Layer ID", "Evidence", "Grounding file"])
        self._tree.itemClicked.connect(self._on_tree_item_clicked)
        self._tree.itemDoubleClicked.connect(self._on_tree_item_double_clicked)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        lv.addWidget(self._tree)

        self._token_label = QLabel("~0 tokens")
        lv.addWidget(self._token_label)

        splitter.addWidget(left)

        # ── right: preview ────────────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Prompt Preview"))
        top_row.addStretch()
        self._copy_all_btn = QPushButton("Copy all")
        self._copy_all_btn.clicked.connect(self._on_copy_all)
        top_row.addWidget(self._copy_all_btn)
        rv.addLayout(top_row)

        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        rv.addWidget(self._preview)

        splitter.addWidget(right)
        splitter.setSizes([320, 780])
        layout.addWidget(splitter)

        signals.set_selected.connect(self._on_set_selected)

    # ── public ────────────────────────────────────────────────────────────────

    # (no public API needed beyond Qt widget interface)

    # ── private ───────────────────────────────────────────────────────────────

    def _on_set_selected(self, _slug: str) -> None:
        if self._recipe_path:
            self._reload()

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select recipe", "", "Recipe files (*.yaml *.yml);;All files (*)"
        )
        if not path:
            return
        existing = self._watcher.files() + self._watcher.directories()
        if existing:
            self._watcher.removePaths(existing)
        self._recipe_path = Path(path)
        self._path_label.setText(path)
        self._reload()

    def _on_file_changed(self, _path: str) -> None:
        self._debounce_timer.start()

    def _reload(self) -> None:
        if not self._recipe_path:
            return

        # Refresh watcher paths
        existing = self._watcher.files() + self._watcher.directories()
        if existing:
            self._watcher.removePaths(existing)

        from evidmgr.services import assembler  # noqa: PLC0415

        try:
            self._corpus_index = self._build_corpus_index()
            self._assembled = assembler.assemble(
                str(self._recipe_path), self._corpus_index
            )
        except Exception:
            logger.exception("Assembly failed")
            self._assembled = None

        # Re-watch recipe + grounding files
        watch_paths = [str(self._recipe_path)]
        try:
            watch_paths += assembler.list_grounding_files(str(self._recipe_path))
        except Exception:
            pass
        self._watcher.addPaths(watch_paths)

        self._populate_tree()
        self._update_preview()

    def _build_corpus_index(self) -> dict[str, list[str]]:
        index: dict[str, list[str]] = {}
        parent = self.window()
        if not hasattr(parent, "_set_manager"):
            return index

        # Pass 1: index every doc by UUID
        for es in parent._set_manager.list_sets():
            docs_dir = es.path / "docs"
            if not docs_dir.exists():
                continue
            for doc_dir in docs_dir.iterdir():
                if not doc_dir.is_dir():
                    continue
                text = self._build_doc_text(doc_dir)
                if text:
                    index[doc_dir.name] = [text]

        # Pass 2: index by tag name (reuse already-read texts)
        for tag in self._tag_service.list_tags():
            texts: list[str] = []
            for item in tag.items:
                doc_texts = index.get(item.doc_uuid, [])
                texts.extend(doc_texts)
            if texts:
                index[tag.name] = texts

        return index

    def _build_doc_text(self, doc_dir: Path) -> str:
        try:
            info_path = doc_dir / "info.yml"
            if not info_path.exists():
                return ""
            with info_path.open("r", encoding="utf-8") as f:
                info = yaml.safe_load(f) or {}

            title = info.get("title") or info.get("label", doc_dir.name)
            authors = info.get("authors", "")
            url = info.get("url", "")

            json_path = doc_dir / "label.json"
            labels_text = ""
            if json_path.exists() and json_path.stat().st_size > 0:
                with json_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                labels = [item["value"] for item in data if item["value"].get("key") != "main"]
                lines = []
                for lbl in labels:
                    opage = lbl.get("opage", "")
                    content = lbl.get("note") or lbl.get("text", "")
                    lines.append(f"- Page {opage}: {content}")
                labels_text = "\n".join(lines)

            block = f"# {title}\n\n"
            if authors:
                block += f"**Author:** {authors}\n\n"
            if url:
                block += f"**Link:** {url}\n\n"
            if labels_text:
                block += labels_text + "\n"
            return block.strip()
        except Exception:
            logger.exception("Failed to build doc text for %s", doc_dir)
            return ""

    def _populate_tree(self) -> None:
        self._tree.clear()
        if not self._assembled or not self._recipe_path:
            return

        from evidmgr.services import assembler  # noqa: PLC0415

        try:
            layers, _fq, _w = assembler.parse_recipe(str(self._recipe_path))
        except Exception:
            return

        def _add_item(parent, layer) -> None:
            item = QTreeWidgetItem(parent)
            item.setText(0, layer.layer_id)

            # Evidence column: tokens + resolved count
            tokens_str = ", ".join(layer.evidence_tokens) if layer.evidence_tokens else "(none)"
            resolved = 0
            for token in layer.evidence_tokens:
                key = token[5:] if token.startswith("evid-") else token
                resolved += len(self._corpus_index.get(key, []))
            item.setText(1, f"{tokens_str} ({resolved} docs)")

            # Grounding column + row colour
            grounding_missing = False
            if layer.grounding_rel:
                item.setText(2, Path(layer.grounding_rel).name)
                if layer.grounding_path and not layer.grounding_path.exists():
                    grounding_missing = True
            else:
                item.setText(2, "")

            if grounding_missing:
                item.setForeground(0, QColor("red"))
            elif resolved == 0:
                item.setForeground(0, QColor("#cc9900"))
            else:
                item.setForeground(0, QColor("#2a9d2a"))

            item.setData(0, Qt.ItemDataRole.UserRole, layer.layer_id)
            item.setData(0, Qt.ItemDataRole.UserRole + 1,
                         str(layer.grounding_path) if layer.grounding_path else None)

            for child in layer.children:
                _add_item(item, child)

        for layer in layers:
            _add_item(self._tree.invisibleRootItem(), layer)

        self._tree.expandAll()
        self._tree.resizeColumnToContents(0)
        self._tree.resizeColumnToContents(2)

        token_count = len(self._assembled.full_text) // 4
        self._token_label.setText(f"~{token_count:,} tokens")

    def _update_preview(self) -> None:
        if self._assembled:
            self._preview.setPlainText(self._assembled.full_text)
        else:
            self._preview.setPlainText("No recipe selected.")

    def _scroll_to_section(self, layer_id: str) -> None:
        if not self._assembled:
            return
        for section in self._assembled.sections:
            if section.layer_id == layer_id:
                self._preview.moveCursor(self._preview.textCursor().MoveOperation.Start)
                cursor = self._preview.document().find(section.anchor)
                if not cursor.isNull():
                    self._preview.setTextCursor(cursor)
                    self._preview.ensureCursorVisible()
                break

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        layer_id = item.data(0, Qt.ItemDataRole.UserRole)
        if layer_id:
            self._scroll_to_section(layer_id)

    def _on_tree_item_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        grounding = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if grounding:
            self._open_file(grounding)
        elif self._recipe_path:
            self._open_file(str(self._recipe_path))

    def _on_tree_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        menu = QMenu(self)

        # Edit actions
        if item:
            grounding = item.data(0, Qt.ItemDataRole.UserRole + 1)
            edit_grounding_action = menu.addAction("Edit grounding file") if grounding else None
        else:
            edit_grounding_action = None
        edit_recipe_action = menu.addAction("Edit recipe YAML") if self._recipe_path else None

        if item or edit_recipe_action:
            menu.addSeparator()

        # Copy actions
        subtree_action = menu.addAction("Copy subtree prompt") if item else None
        full_action = menu.addAction("Copy full prompt")

        action = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if action is None:
            return

        if edit_grounding_action and action is edit_grounding_action:
            self._open_file(item.data(0, Qt.ItemDataRole.UserRole + 1))
            return
        if edit_recipe_action and action is edit_recipe_action:
            self._open_file(str(self._recipe_path))
            return

        from evidmgr.services import assembler  # noqa: PLC0415

        if action is full_action:
            if self._assembled:
                QApplication.clipboard().setText(self._assembled.full_text)
        elif subtree_action and action is subtree_action and item:
            layer_id = item.data(0, Qt.ItemDataRole.UserRole)
            if layer_id and self._recipe_path:
                try:
                    sub = assembler.assemble_subtree(
                        str(self._recipe_path), layer_id, self._corpus_index
                    )
                    QApplication.clipboard().setText(sub.full_text)
                except Exception:
                    logger.exception("assemble_subtree failed")

    def _open_file(self, path: str) -> None:
        import shutil, subprocess  # noqa: PLC0415
        from pathlib import Path as _Path  # noqa: PLC0415

        parent = self.window()
        editor = parent._config.editor if hasattr(parent, "_config") else "code"
        if shutil.which(editor):
            cmd = [editor]
            # For VS Code, inject tag autocomplete schema when opening the recipe
            if "code" in _Path(editor).name and self._recipe_path and _Path(path) == self._recipe_path:
                self._inject_vscode_schema(self._recipe_path)
                cmd.append(str(self._recipe_path.parent))
            cmd.append(path)
            subprocess.Popen(cmd)  # noqa: S603
        else:
            from PySide6.QtCore import QUrl  # noqa: PLC0415
            from PySide6.QtGui import QDesktopServices  # noqa: PLC0415

            if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
                from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

                QMessageBox.warning(self, "Cannot open file", f"No application found to open:\n{path}")

    def _inject_vscode_schema(self, recipe_path: Path) -> None:
        import json  # noqa: PLC0415

        tags = [t.name for t in self._tag_service.list_tags()]

        evidence_items: dict = {"type": "string"}
        if tags:
            evidence_items["anyOf"] = [
                {"enum": tags, "description": "Tag name"},
                {"pattern": "^evid-", "description": "Document UUID token (evid-<uuid>)"},
            ]

        layer_def: dict = {
            "type": "object",
            "required": ["id"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string"},
                "evidence": {"type": "array", "items": evidence_items},
                "grounding": {
                    "type": "string",
                    "description": "Path to grounding file, relative to this recipe",
                },
                "layers": {"type": "array", "items": {"$ref": "#/$defs/layer"}},
            },
        }

        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Evidmgr Recipe",
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "layers": {"type": "array", "items": {"$ref": "#/$defs/layer"}},
                "final_question": {
                    "type": "string",
                    "description": "Path to final question file, relative to this recipe",
                },
            },
            "$defs": {"layer": layer_def},
        }

        vscode_dir = recipe_path.parent / ".vscode"
        vscode_dir.mkdir(exist_ok=True)

        schema_path = vscode_dir / "recipe-schema.json"
        schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

        settings_path = vscode_dir / "settings.json"
        settings: dict = {}
        if settings_path.exists():
            try:
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        yaml_schemas = settings.get("yaml.schemas", {})
        yaml_schemas["./.vscode/recipe-schema.json"] = recipe_path.name
        settings["yaml.schemas"] = yaml_schemas
        settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def _on_copy_all(self) -> None:
        QApplication.clipboard().setText(self._preview.toPlainText())
