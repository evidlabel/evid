"""Prompt Builder tab — recipe-driven evidence assembly, multi-recipe stack."""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from PySide6.QtCore import QFileSystemWatcher, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from evid.gui.signals import AppSignals
    from evid.services.tag_service import TagService

logger = logging.getLogger(__name__)

_SETTINGS_KEY = "prompt_tab/open_recipes"


# ── helpers ───────────────────────────────────────────────────────────────────


def _collect_layer_text_hashes(
    layers: list,
    corpus: dict[str, list[str]],
    seen: set[int],
) -> None:
    """Add text hashes for all evidence tokens in *layers* into *seen*."""
    for layer in layers:
        for token in layer.evidence_tokens:
            key = token.removeprefix("evid-")
            for text in corpus.get(key, []):
                seen.add(hash(text))
        _collect_layer_text_hashes(layer.children, corpus, seen)


# ── RecipePanel ───────────────────────────────────────────────────────────────


class RecipePanel(QWidget):
    """Collapsible panel for a single recipe YAML file."""

    closed = Signal()
    path_changed = Signal(Path)
    collapse_toggled = Signal()
    move_up_requested = Signal()
    move_down_requested = Signal()
    # (recipe_path_str, file_path_str) — open file_path in editor
    open_file_requested = Signal(str, str)
    # layer_id — scroll preview to that section
    scroll_requested = Signal(str)
    # (recipe_path_str, layer_id or "__full__") — copy to clipboard
    copy_subtree_requested = Signal(str, str)

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = path
        self._collapsed = False
        self._setup_ui()

    # ── public ────────────────────────────────────────────────────────────────

    @property
    def path(self) -> Path:
        return self._path

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def populate_tree(self, corpus_index: dict[str, list[str]]) -> None:
        """Repopulate the layer tree for this panel's recipe."""
        from evid.services import assembler

        self._tree.clear()
        try:
            layers, _fq, _w = assembler.parse_recipe(str(self._path))
        except Exception:
            logger.exception("Failed to parse %s", self._path)
            return

        def _add(parent_item, layer) -> None:
            item = QTreeWidgetItem(parent_item)
            item.setText(0, layer.layer_id)

            tokens_str = (
                ", ".join(layer.evidence_tokens) if layer.evidence_tokens else "(none)"
            )
            resolved = sum(
                len(corpus_index.get(t.removeprefix("evid-"), []))
                for t in layer.evidence_tokens
            )
            item.setText(1, f"{tokens_str} ({resolved} docs)")

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
            item.setData(
                0,
                Qt.ItemDataRole.UserRole + 1,
                str(layer.grounding_path) if layer.grounding_path else None,
            )
            for child in layer.children:
                _add(item, child)

        for layer in layers:
            _add(self._tree.invisibleRootItem(), layer)

        self._tree.expandAll()
        self._tree.resizeColumnToContents(0)
        self._tree.resizeColumnToContents(2)

    # ── private ───────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # header
        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(4, 3, 4, 3)
        hl.setSpacing(3)

        self._toggle_btn = QPushButton("▼")
        self._toggle_btn.setFixedWidth(24)
        self._toggle_btn.setFlat(True)
        self._toggle_btn.clicked.connect(self._on_toggle)

        self._path_label = QLabel(str(self._path))
        self._path_label.setWordWrap(False)
        self._path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._browse_btn = QPushButton("…")
        self._browse_btn.setFixedWidth(30)
        self._browse_btn.clicked.connect(self._on_browse)

        self._up_btn = QPushButton("↑")
        self._up_btn.setFixedWidth(24)
        self._up_btn.setFlat(True)
        self._up_btn.clicked.connect(self.move_up_requested.emit)

        self._down_btn = QPushButton("↓")
        self._down_btn.setFixedWidth(24)
        self._down_btn.setFlat(True)
        self._down_btn.clicked.connect(self.move_down_requested.emit)

        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedWidth(24)
        self._close_btn.setFlat(True)
        self._close_btn.clicked.connect(self.closed.emit)

        hl.addWidget(self._toggle_btn)
        hl.addWidget(self._path_label, 1)
        hl.addWidget(self._browse_btn)
        hl.addWidget(self._up_btn)
        hl.addWidget(self._down_btn)
        hl.addWidget(self._close_btn)

        # body: tree
        self._body = QWidget()
        bl = QVBoxLayout(self._body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Layer ID", "Evidence", "Grounding file"])
        self._tree.setMaximumHeight(220)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        bl.addWidget(self._tree)

        # separator line
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setObjectName("recipe-sep")

        layout.addWidget(header)
        layout.addWidget(self._body)
        layout.addWidget(sep)

    def _on_toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._body.setVisible(not self._collapsed)
        self._toggle_btn.setText("▶" if self._collapsed else "▼")
        self.collapse_toggled.emit()

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select recipe",
            str(self._path.parent),
            "Recipe files (*.yaml *.yml);;All files (*)",
        )
        if path:
            self._path = Path(path)
            self._path_label.setText(path)
            self.path_changed.emit(self._path)

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        layer_id = item.data(0, Qt.ItemDataRole.UserRole)
        if layer_id:
            self.scroll_requested.emit(layer_id)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        grounding = item.data(0, Qt.ItemDataRole.UserRole + 1)
        target = grounding or str(self._path)
        self.open_file_requested.emit(str(self._path), target)

    def _on_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        menu = QMenu(self)

        grounding = item.data(0, Qt.ItemDataRole.UserRole + 1) if item else None
        edit_grounding = menu.addAction("Edit grounding file") if grounding else None
        edit_recipe = menu.addAction("Edit recipe YAML")
        menu.addSeparator()
        subtree_action = (
            menu.addAction("Copy subtree prompt")
            if item and item.data(0, Qt.ItemDataRole.UserRole)
            else None
        )
        full_action = menu.addAction("Copy full prompt")

        action = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if action is None:
            return

        if edit_grounding and action is edit_grounding:
            self.open_file_requested.emit(str(self._path), grounding)
        elif action is edit_recipe:
            self.open_file_requested.emit(str(self._path), str(self._path))
        elif subtree_action and action is subtree_action:
            layer_id = item.data(0, Qt.ItemDataRole.UserRole)
            if layer_id:
                self.copy_subtree_requested.emit(str(self._path), layer_id)
        elif action is full_action:
            self.copy_subtree_requested.emit("", "__full__")


# ── RecipeStack ───────────────────────────────────────────────────────────────


class RecipeStack(QWidget):
    """Vertical stack of RecipePanel widgets.

    Callers use ``add_recipe()`` to create a panel, then connect the returned
    panel's signals before triggering a reload.
    """

    stack_changed = Signal()  # panels removed / reordered / path or collapse changed
    add_requested = Signal()  # user clicked "+ Add recipe"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._panels: list[RecipePanel] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # container that holds panels; stretch pushes them to the top
        self._panel_widget = QWidget()
        self._panel_layout = QVBoxLayout(self._panel_widget)
        self._panel_layout.setContentsMargins(0, 0, 0, 0)
        self._panel_layout.setSpacing(0)
        self._panel_layout.addStretch()

        outer.addWidget(self._panel_widget)

        add_btn = QPushButton("+ Add recipe")
        add_btn.clicked.connect(self.add_requested.emit)
        outer.addWidget(add_btn)

    # ── public ────────────────────────────────────────────────────────────────

    def add_recipe(self, path: Path) -> RecipePanel:
        """Insert a new panel at the bottom of the stack and return it.

        The caller is responsible for connecting the panel's ``open_file_requested``,
        ``scroll_requested``, and ``copy_subtree_requested`` signals, and for
        triggering a reload.
        """
        panel = RecipePanel(path)
        idx = len(self._panels)
        self._panels.append(panel)
        # insert before the trailing stretch spacer
        self._panel_layout.insertWidget(idx, panel)

        panel.closed.connect(lambda: self._do_remove(panel))
        panel.move_up_requested.connect(lambda: self._do_move(panel, -1))
        panel.move_down_requested.connect(lambda: self._do_move(panel, 1))
        panel.path_changed.connect(lambda _: self.stack_changed.emit())
        panel.collapse_toggled.connect(self.stack_changed.emit)

        return panel

    def get_panels(self) -> list[RecipePanel]:
        return list(self._panels)

    def get_paths(self) -> list[Path]:
        return [p.path for p in self._panels]

    # ── private ───────────────────────────────────────────────────────────────

    def _do_remove(self, panel: RecipePanel) -> None:
        if panel not in self._panels:
            return
        self._panels.remove(panel)
        self._panel_layout.removeWidget(panel)
        panel.deleteLater()
        self.stack_changed.emit()

    def _do_move(self, panel: RecipePanel, direction: int) -> None:
        idx = self._panels.index(panel)
        new_idx = idx + direction
        if not (0 <= new_idx < len(self._panels)):
            return
        self._panels.pop(idx)
        self._panels.insert(new_idx, panel)
        for p in self._panels:
            self._panel_layout.removeWidget(p)
        for i, p in enumerate(self._panels):
            self._panel_layout.insertWidget(i, p)
        self.stack_changed.emit()


# ── PromptTab ─────────────────────────────────────────────────────────────────


class PromptTab(QWidget):
    def __init__(
        self,
        tag_service: TagService,
        signals: AppSignals,
    ) -> None:
        super().__init__()
        self._tag_service = tag_service
        self._signals = signals
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

        # ── left: recipe stack ─────────────────────────────────────────────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)

        self._recipe_stack = RecipeStack()
        self._recipe_stack.stack_changed.connect(self._on_stack_changed)
        self._recipe_stack.add_requested.connect(self._on_add_recipe)

        scroll = QScrollArea()
        scroll.setWidget(self._recipe_stack)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lv.addWidget(scroll, 1)

        self._token_label = QLabel("~0 tokens")
        lv.addWidget(self._token_label)

        splitter.addWidget(left)

        # ── right: preview ─────────────────────────────────────────────────
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
        signals.labels_updated.connect(self._on_labels_updated)

        self._restore_session()

    # ── public ────────────────────────────────────────────────────────────────

    # (no public API needed beyond Qt widget interface)

    # ── private ───────────────────────────────────────────────────────────────

    def _on_set_selected(self, _slug: str) -> None:
        self._reload()

    def _on_labels_updated(self, _set_slug: str, _doc_uuid: str) -> None:
        self._reload()

    def _on_stack_changed(self) -> None:
        """Handles remove / reorder / path-change / collapse from the stack."""
        self._save_session()
        self._reload()

    def _on_add_recipe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select recipe YAML",
            "",
            "Recipe files (*.yaml *.yml);;All files (*)",
        )
        if path:
            self._open_recipe(Path(path))

    def _open_recipe(self, path: Path) -> None:
        """Create a panel for *path*, wire its signals, persist, and reload."""
        panel = self._recipe_stack.add_recipe(path)
        panel.open_file_requested.connect(self._on_panel_open_file)
        panel.scroll_requested.connect(self._on_panel_scroll)
        panel.copy_subtree_requested.connect(self._on_panel_copy_subtree)
        self._save_session()
        self._reload()

    def _on_file_changed(self, _path: str) -> None:
        self._debounce_timer.start()

    def _reload(self) -> None:
        panels = self._recipe_stack.get_panels()
        if not panels:
            self._preview.setPlainText("No recipe selected.")
            self._token_label.setText("~0 tokens")
            return

        # Rebuild file watcher
        existing = self._watcher.files() + self._watcher.directories()
        if existing:
            self._watcher.removePaths(existing)

        from evid.services import assembler

        try:
            self._corpus_index = self._build_corpus_index()
        except Exception:
            logger.exception("Failed to build corpus index")
            self._corpus_index = {}

        for panel in panels:
            try:
                panel.populate_tree(self._corpus_index)
            except Exception:
                logger.exception("Failed to populate tree for %s", panel.path)

        combined = self._build_combined_text(panels)
        self._preview.setPlainText(combined or "No content assembled.")

        token_count = len(combined) // 4
        n = len(panels)
        label = f"~{token_count:,} tokens across {n} recipe{'s' if n != 1 else ''}"
        self._token_label.setText(label)

        # Re-watch all recipe + grounding files
        watch_paths = [str(p.path) for p in panels]
        for p in panels:
            with contextlib.suppress(Exception):
                watch_paths += assembler.list_grounding_files(str(p.path))
        self._watcher.addPaths(watch_paths)

    def _build_combined_text(self, panels: list[RecipePanel]) -> str:
        """Assemble all panels in order, deduplicating evidence text across recipes.

        Structure:
          ### [recipe: filename.yaml] ###
          <layers for recipe 1>
          ### [recipe: filename.yaml] ###
          <layers for recipe 2>
          ...
          ### [final_question] ###
          <final_question from last recipe that has one>
        """
        from evid.services import assembler

        parts: list[str] = []
        seen_text_hashes: set[int] = set()
        last_final_question_text: str | None = None

        for panel in panels:
            # Filter corpus to exclude texts already included by earlier panels
            filtered: dict[str, list[str]] = {
                key: [t for t in texts if hash(t) not in seen_text_hashes]
                for key, texts in self._corpus_index.items()
                if any(hash(t) not in seen_text_hashes for t in texts)
            }

            try:
                assembled = assembler.assemble(str(panel.path), filtered)
            except Exception:
                logger.exception("Assembly failed for %s", panel.path)
                continue

            # Split final_question out — emitted once at the very end
            content_sections = [
                s for s in assembled.sections if s.kind != "final_question"
            ]
            fq_sections = [s for s in assembled.sections if s.kind == "final_question"]
            content_text = "\n\n".join(s.text for s in content_sections)

            if content_text.strip():
                parts.append(f"### [recipe: {panel.path.name}] ###")
                parts.append(content_text)

            if fq_sections:
                last_final_question_text = fq_sections[-1].text

            # Track hashes of texts that were available to this panel
            try:
                layers, _, _ = assembler.parse_recipe(str(panel.path))
                _collect_layer_text_hashes(layers, filtered, seen_text_hashes)
            except Exception:
                pass

        # Emit final_question exactly once at the very end
        if last_final_question_text:
            parts.append(last_final_question_text)
        elif panels:
            parts.append(
                "### [final_question] ###\n\n"
                "<!-- No final_question defined in any open recipe -->"
            )

        return "\n\n".join(parts)

    def _build_corpus_index(self) -> dict[str, list[str]]:
        index: dict[str, list[str]] = {}
        parent = self.window()
        if not hasattr(parent, "_set_manager"):
            return index

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
            try:
                with info_path.open("r", encoding="utf-8") as f:
                    info = yaml.safe_load(f) or {}
            except yaml.YAMLError:
                logger.debug("Skipping bad info.yml in %s", doc_dir.name)
                return ""

            title = info.get("title") or info.get("label", doc_dir.name)
            authors = info.get("authors", "")
            url = info.get("url", "")

            json_path = doc_dir / "label.json"
            labels_text = ""
            if json_path.exists() and json_path.stat().st_size > 0:
                with json_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                labels = [
                    item["value"] for item in data if item["value"].get("key") != "main"
                ]
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

    def _scroll_to_section(self, layer_id: str) -> None:
        cursor = self._preview.document().find(f"### [{layer_id}]")
        if not cursor.isNull():
            self._preview.setTextCursor(cursor)
            self._preview.ensureCursorVisible()

    # ── panel signal handlers ─────────────────────────────────────────────────

    def _on_panel_open_file(self, recipe_path_str: str, file_path: str) -> None:
        self._open_file(file_path, recipe_path_str)

    def _on_panel_scroll(self, layer_id: str) -> None:
        self._scroll_to_section(layer_id)

    def _on_panel_copy_subtree(self, recipe_path_str: str, layer_id: str) -> None:
        if layer_id == "__full__":
            QApplication.clipboard().setText(self._preview.toPlainText())
            return
        from evid.services import assembler

        try:
            sub = assembler.assemble_subtree(
                recipe_path_str, layer_id, self._corpus_index
            )
            QApplication.clipboard().setText(sub.full_text)
        except Exception:
            logger.exception("assemble_subtree failed for layer %s", layer_id)

    def _on_copy_all(self) -> None:
        QApplication.clipboard().setText(self._preview.toPlainText())

    # ── persistence ───────────────────────────────────────────────────────────

    def _save_session(self) -> None:
        settings = QSettings("evidmgr", "evidmgr")
        settings.setValue(
            _SETTINGS_KEY, [str(p) for p in self._recipe_stack.get_paths()]
        )

    def _restore_session(self) -> None:
        settings = QSettings("evidmgr", "evidmgr")
        raw = settings.value(_SETTINGS_KEY, [])
        if isinstance(raw, str):
            paths = [raw] if raw else []
        elif isinstance(raw, list):
            paths = raw
        else:
            paths = []

        for path_str in paths:
            p = Path(path_str)
            if p.exists():
                self._open_recipe(p)

    # ── editor / VS Code integration ──────────────────────────────────────────

    def _open_file(self, path: str, recipe_path_str: str = "") -> None:
        import shutil
        import subprocess
        from pathlib import Path as _Path

        parent = self.window()
        editor = parent._config.editor if hasattr(parent, "_config") else "code"
        if shutil.which(editor):
            cmd = [editor]
            recipe_path = _Path(recipe_path_str) if recipe_path_str else None
            if (
                "code" in _Path(editor).name
                and recipe_path
                and _Path(path) == recipe_path
            ):
                self._inject_vscode_schema(recipe_path)
                cmd.append(str(recipe_path.parent))
            cmd.append(path)
            subprocess.Popen(cmd)
        else:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(
                    self, "Cannot open file", f"No application found to open:\n{path}"
                )

    def _inject_vscode_schema(self, recipe_path: Path) -> None:
        tags = [t.name for t in self._tag_service.list_tags()]

        evidence_items: dict = {"type": "string"}
        if tags:
            evidence_items["anyOf"] = [
                {"enum": tags, "description": "Tag name"},
                {
                    "pattern": "^evid-",
                    "description": "Document UUID token (evid-<uuid>)",
                },
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
            with contextlib.suppress(Exception):
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
        yaml_schemas = settings.get("yaml.schemas", {})
        yaml_schemas["./.vscode/recipe-schema.json"] = recipe_path.name
        settings["yaml.schemas"] = yaml_schemas
        settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
