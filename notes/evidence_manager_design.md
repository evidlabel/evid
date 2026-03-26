# Evidence Manager — Design Document

A single local Qt application integrating **evid**, **vecdb**, and **did** into a unified
tool for gathering, labelling, searching, anonymizing, and prompting over evidence
documents.

---

## 1. Goals

- Collect general reference documents (laws, guidelines, papers) and case-specific
  documents (PII-bearing reports, statements) under one roof.
- Give every document a stable, reproducible UUID; store structured metadata in
  `info.yml` (evid convention, preserved as-is).
- Extract text through the evid typst pipeline so labels/citations stay machine-readable.
- Index each document into a per-set ChromaDB instance for vector search.
- For case sets, pseudonymize PII via presidio + spaCy (did), with a versioned YAML
  history so the mapping is auditable and replaceable.
- Build prompts by search result, selection, or tag — with one-click toggle between
  anonymized and raw output.

---

## 2. Evidence Set Types

### 2a. Normal set
Standard document collection. Any document type; full text always available.

### 2b. Anonymous set
Same as a normal set with three additions:

1. An `anon/` folder exists at the set root holding **entity YAML files**.
2. A `current.yml` symlink (or plain text file containing a filename) points to the
   active YAML used for pseudonymization.
3. The GUI shows an **Anonymize** toggle. When on, all text exported through the
   Prompt Builder or Export panel is run through `did pseudo` against the active YAML
   before delivery.

The anonymization layer is **additive and reversible**: original PDFs are never modified.
All substitution is applied at export time from the YAML mapping.

---

## 3. On-Disk Folder Structure

```
~/.local/share/evidmgr/           # or user-chosen root
  sets/
    <set-slug>/
      set.yml                     # set metadata: name, type, created, description
      docs/
        <uuid>/
          info.yml                # date, label, tags, source_type (law|guideline|paper|case|other)
          original.pdf            # original file, never modified
          <uuid>.typ              # evid-extracted typst file
          label.json              # written by typst query
          label.bib               # generated BibTeX
      anon/                       # only for anon sets
        <ISO-timestamp>_entities.yml  # entity map produced by did extract
        <ISO-timestamp>_entities.yml  # newer run, different docs or corrections
        current                   # plain text: filename of active YAML (no symlink dependency)
      vecdb/
        chroma.sqlite3            # chromadb persistent client
        <collection-uuid>/        # chromadb internal files
```

### set.yml schema

```yaml
name: "Hansen Case 2024"
slug: "hansen-case-2024"
type: anon          # or: normal
created: "2024-11-03T14:22:00"
description: "Personal injury claim, district court"
anon_language: da   # language hint for did/presidio; omit for normal sets
```

### info.yml schema (per document — extends evid convention)

```yaml
uuid: "a3f9c1d2-..."
added: "2024-11-03T15:00:00"
label: "Police report 14/2024"
tags: [police, incident, primary]
source_type: case             # law | guideline | paper | case | other
source_url: ""
notes: ""
indexed: true                 # set by VecService after embedding
anon_pending: false           # set true when AnonService queues extraction
```

### Entity YAML schema (produced by did, managed by AnonService)

```yaml
generated: "2024-11-04T09:10:00"
docs_included: ["a3f9c1d2", "b7e2a0f1"]
language: da
entities:
  - original: "Lars Hansen"
    variants: ["Hansen, Lars", "L. Hansen"]
    entity_type: PERSON
    replacement: "Person A"
  - original: "Roskildevej 14, 2620 Albertslund"
    variants: []
    entity_type: ADDRESS
    replacement: "Address 1"
  - original: "301284-1234"
    variants: []
    entity_type: CPR
    replacement: "[CPR REDACTED]"
```

---

## 4. Python Package & Dependency Stack

```toml
[project]
name = "evidmgr"
dependencies = [
    "evid @ git+https://github.com/evidlabel/evid.git",
    "did @ git+https://github.com/evidlabel/did.git",
    "vecdb @ git+https://github.com/evidlabel/vecdb.git",
    "chromadb",
    "presidio-analyzer",
    "presidio-anonymizer",
    "spacy",
    "PyQt6",
    "pyyaml",
    "python-slugify",
]
```

Post-install: download spaCy models needed by did (e.g. `en_core_web_lg`,
`da_core_news_lg`).

---

## 5. Service Layer

All services are plain Python classes instantiated at startup and passed to panels via
dependency injection (not singletons, to make testing easier).

### 5a. SetManager

```python
class SetManager:
    root: Path  # base sets/ directory

    def list_sets(self) -> list[SetInfo]: ...
    def create_set(self, name: str, set_type: SetType, lang: str = "da") -> EvidenceSet: ...
    def load_set(self, slug: str) -> EvidenceSet: ...
    def delete_set(self, slug: str) -> None: ...
    def update_set_meta(self, slug: str, **kwargs) -> None: ...
```

`EvidenceSet` is a lightweight dataclass holding the set path and parsed `set.yml`. It
does not load documents eagerly.

### 5b. DocIngester

Called when the user drops or selects a PDF to add to a set.

```python
class DocIngester:
    def ingest(
        self,
        pdf_path: Path,
        evidence_set: EvidenceSet,
        label: str = "",
        tags: list[str] = (),
        source_type: str = "other",
    ) -> Document:
        # 1. Generate UUID (evid convention: uuid5 from file content hash)
        # 2. Create docs/<uuid>/ folder
        # 3. Copy PDF as original.pdf
        # 4. Write info.yml
        # 5. Run evid PDF-to-typst extraction → <uuid>.typ
        # 6. Run typst compile + typst query → label.json
        # 7. Convert label.json → label.bib
        # 8. Call VecService.index_doc(doc)
        # 9. If set is anon: mark info.yml anon_pending=True, emit signal for AnonService
        ...
```

The ingestion runs in a `QThread` worker to keep the UI responsive. A
`QProgressDialog` shows the current step.

### 5c. VecService

Wraps vecdb. Each evidence set gets its own ChromaDB persistent client stored in
`<set-root>/vecdb/`.

```python
class VecService:
    def get_collection(self, evidence_set: EvidenceSet) -> chromadb.Collection: ...

    def index_doc(self, doc: Document) -> None:
        # Chunk the extracted typst text (strip typst markup first)
        # Embed with chromadb's default embedding function
        # Store: id=f"{doc.uuid}:{chunk_idx}", metadata={uuid, label, tags, source_type}
        ...

    def query(
        self,
        evidence_set: EvidenceSet,
        query_text: str,
        n_results: int = 10,
        filter_tags: list[str] = (),
        filter_source_type: str = "",
    ) -> list[VecResult]:
        # Returns list of (doc_uuid, chunk_text, score, metadata)
        ...

    def remove_doc(self, evidence_set: EvidenceSet, doc_uuid: str) -> None: ...
```

**Chunking strategy**: split typst text by paragraph (double newline), then by sentence
if chunks exceed 512 tokens. Store `chunk_idx` and `char_start` in Chroma metadata so
the UI can highlight the matching passage in the document viewer.

### 5d. AnonService

Wraps did. Manages the `anon/` YAML history and applies pseudonymization.

```python
class AnonService:
    def run_extract(
        self,
        evidence_set: EvidenceSet,
        doc_uuids: list[str],
        language: str = "da",
    ) -> Path:
        # Concatenates typst texts of specified docs into a temp file
        # Calls did extract (Python API, not subprocess) on temp file
        # Saves result as anon/<ISO-timestamp>_entities.yml
        # Does NOT overwrite existing YAMLs
        # Returns path to new YAML
        ...

    def list_yamls(self, evidence_set: EvidenceSet) -> list[AnonYaml]: ...

    def set_current(self, evidence_set: EvidenceSet, yaml_path: Path) -> None:
        # Writes filename to anon/current
        ...

    def get_current_yaml(self, evidence_set: EvidenceSet) -> AnonYaml | None: ...

    def pseudonymize(self, text: str, evidence_set: EvidenceSet) -> str:
        # Loads current YAML, applies did pseudo
        # Returns anonymized string
        ...

    def deanonymize(self, text: str, evidence_set: EvidenceSet) -> str:
        # Reverse substitution from current YAML (replacement → original)
        ...
```

**Key design decision**: `did extract` and `did pseudo` are called via their Python API
(importing from the `did` package), not via `subprocess`. This avoids shell overhead
and lets exceptions propagate cleanly.

---

## 6. Qt App Window Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Menu bar: File | Set | Tools | Help                            │
├──────────────┬──────────────────────────────────────────────────┤
│  Sidebar     │  Main area (QStackedWidget)                      │
│              │                                                  │
│  ▾ Evidence  │  [Docs] [Search] [Anonymize] [Prompts] tabs     │
│    sets      │                                                  │
│  ──────────  │                                                  │
│  • Hansen    │                                                  │
│    Case      │                                                  │
│  • EU GDPR   │                                                  │
│    Law       │                                                  │
│  ──────────  │                                                  │
│  [+ New set] │                                                  │
│              │                                                  │
│  Set type:   │                                                  │
│  🔒 Anon     │                                                  │
│              │                                                  │
│  Anon:  ●   │                                                  │
│  [ON / OFF]  │                                                  │
└──────────────┴──────────────────────────────────────────────────┘
```

The **Anon toggle** in the sidebar is only shown for anonymous sets. When toggled ON,
the `AnonService.pseudonymize()` path is activated for all prompt and export output.
The toggle state is not persisted to disk — it resets to OFF on launch (safe default).

The **tab bar** shows only the tabs relevant to the active set type: "Anonymize" is
hidden for normal sets.

---

## 7. Panel Designs

### 7a. Docs panel (QSplitter: left list + right detail)

**Left pane — document list**:
- `QTableWidget` or `QTreeWidget` with columns: Label | Tags | Type | Date | Indexed | Anon
- Filter bar above: free-text label filter + tag chip filter + source_type dropdown
- Toolbar: `[Add PDF]` `[Label]` `[Tag]` `[Delete]` `[Open typst]`
- Drag-and-drop PDF onto the list triggers ingestion

**Right pane — document detail**:
- Read-only fields: UUID, file path, date added
- Editable: label (QLineEdit), tags (tag chip editor), source_type (QComboBox), notes (QTextEdit)
- Labels section: collapsible table showing `label.json` entries (key, text, note)
- Actions: `[Open in editor]` (launches system editor on .typ file), `[Regenerate bib]`, `[Re-index]`

**Anon sub-panel** (shown only in anon sets, only when a doc is selected):
- Badge: "PII extracted" or "Pending extraction"
- `[Run extraction]` button → calls `AnonService.run_extract([selected_uuid])`
- Link to the entity entries found in the current YAML for this doc

### 7b. Search panel

Two modes switchable via a `QTabBar`:

**Meta search**:
- Filter controls: tag multi-select, source_type, date range, label text (regex)
- Results list mirrors the Docs panel list format
- Selection from results feeds into the Prompt Builder

**Vector search**:
- `QTextEdit` for query input (supports multi-sentence queries)
- Sliders: result count (5–50), score threshold
- Optional filters: tag, source_type
- Results list: doc label | score badge | chunk preview (first 120 chars)
- Clicking a result opens the doc detail panel with the matching chunk highlighted

Both modes: `[Add to prompt]` button sends selected results to the Prompt Builder.

### 7c. Anonymize panel (anon sets only)

Three sub-sections:

**YAML history** (left column):
- List of `anon/<timestamp>_entities.yml` files, newest first
- Current YAML marked with a ★ badge
- Per-entry actions: `[Set as current]`, `[View diff vs previous]`
- `[Generate new YAML]` button: opens doc multi-select dialog, then calls
  `AnonService.run_extract(...)`

**Entity editor** (right column, loads current YAML):
- `QTableWidget`: Original | Type | Replacement | Variants
- Cells are editable — changes write back to the YAML on save
- `[Save]` button commits edits; does not auto-save to avoid accidental overwrite
- `[Merge variants]` — opens dialog to collapse two entity rows into one
- `[Add manual entity]` — manually specify a replacement for a term did missed

**Preview strip** (bottom):
- Paste or load a text snippet; live-render the anonymized version using current YAML
- Side-by-side: original vs anonymized
- Toggle to show inverse (anonymized → original via reverse map)

### 7d. Prompt Builder panel

Three source modes (radio buttons at top):

**By search** — pulls from the last Search panel result set. A `QListWidget` of
results; drag to re-order; checkbox to include/exclude each.

**By selection** — a `QListWidget` of manually chosen documents (drag from Docs panel or
click `[Add to prompt]`). Individual label entries (from label.json) can be
sub-selected.

**By tag** — a tag multi-select that auto-includes all documents bearing those tags.
Live count shows how many chunks will be included.

**Prompt construction area**:
- Template `QTextEdit` with variable placeholders: `{{evidence}}`, `{{task}}`
- `[Insert evidence block]` button inserts the evidence as a formatted block at cursor
- Live character/token counter
- `[Preview]` renders the final prompt in a read-only pane

**Export controls**:
- Format: plain text | markdown | BibTeX references only
- Anon toggle (mirrors sidebar toggle)
- `[Copy to clipboard]` | `[Save as file...]` | `[Export BibTeX]`

---

## 8. Document Ingestion Pipeline (step by step)

```
User drops PDF
    │
    ▼
DocIngester.ingest()
    │
    ├─ 1. Hash PDF content → uuid5 → doc UUID
    │
    ├─ 2. mkdir docs/<uuid>/; copy PDF as original.pdf
    │
    ├─ 3. Write info.yml (label, tags, source_type, anon_pending=False)
    │
    ├─ 4. evid.extract(pdf_path) → <uuid>.typ
    │       (uses evid's PDF-to-typst pipeline; preserves existing evid convention)
    │
    ├─ 5. typst compile + typst query → label.json (empty initially)
    │
    ├─ 6. json-to-bib → label.bib
    │
    ├─ 7. VecService.index_doc()
    │       chunk typst text → embed → store in <set>/vecdb/
    │       update info.yml: indexed=true
    │
    └─ 8. [If anon set]
            update info.yml: anon_pending=true
            emit Qt signal → AnonPanel shows "pending" badge
            (extraction is manual/on-demand, not automatic)
```

The ingestion worker emits `progress(step, total, message)` signals to drive a
`QProgressDialog`. On error, a `QMessageBox` shows the failure with the traceback.

---

## 9. Anonymization Pipeline (step by step)

```
User selects docs in Anon panel → [Generate new YAML]
    │
    ▼
AnonService.run_extract(doc_uuids)
    │
    ├─ 1. Load <uuid>.typ text for each doc
    │
    ├─ 2. Strip typst markup → plain text
    │
    ├─ 3. did.extract(text, language=set.anon_language)
    │       → uses presidio AnalyzerEngine + spaCy NER
    │       → groups variants via rapidfuzz
    │       → returns entity list
    │
    ├─ 4. Auto-assign replacement labels (Person A/B/C..., Address 1/2..., etc.)
    │
    ├─ 5. Save as anon/<ISO-timestamp>_entities.yml
    │       Does NOT set as current automatically
    │
    └─ 6. Emit signal → AnonPanel refreshes YAML history list


User reviews YAML in entity editor → edits replacements → [Save]
    → writes changes back to the YAML file

User clicks [Set as current]
    → AnonService.set_current() → writes filename to anon/current

At export / prompt build with Anon ON:
    AnonService.pseudonymize(text)
    → loads current YAML
    → calls did.pseudo(text, yaml_path)
    → returns substituted text
```

---

## 10. Vector Search Integration

Each evidence set owns one ChromaDB **persistent client** mounted at
`<set-root>/vecdb/`. The collection name is fixed as `"docs"`.

**Document chunk metadata stored per chunk**:
```python
{
    "doc_uuid": "a3f9c1d2-...",
    "label": "Police report 14/2024",
    "tags": "police,incident",       # comma-joined for Chroma's string filter
    "source_type": "case",
    "chunk_idx": 3,
    "char_start": 1420,
}
```

**Query flow**:
```python
results = collection.query(
    query_texts=[query],
    n_results=n,
    where={"source_type": {"$eq": filter_source_type}} if filter_source_type else None,
)
# Map doc_uuid back to Document object via SetManager
# Return VecResult(doc, chunk_text, score, char_start)
```

**When a document is deleted**: `VecService.remove_doc()` deletes all chunks where
`metadata["doc_uuid"] == uuid`. `collection.delete(where={"doc_uuid": uuid})`.

**When a document is re-labelled**: chunk metadata is updated via
`collection.update(ids=[...], metadatas=[...])`.

---

## 11. Data Models (Python dataclasses)

```python
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from enum import Enum

class SetType(str, Enum):
    NORMAL = "normal"
    ANON = "anon"

class SourceType(str, Enum):
    LAW = "law"
    GUIDELINE = "guideline"
    PAPER = "paper"
    CASE = "case"
    OTHER = "other"

@dataclass
class EvidenceSet:
    name: str
    slug: str
    path: Path
    set_type: SetType
    created: datetime
    description: str = ""
    anon_language: str = "da"

@dataclass
class Document:
    uuid: str
    path: Path              # docs/<uuid>/ folder
    label: str
    tags: list[str]
    source_type: SourceType
    added: datetime
    indexed: bool = False
    anon_pending: bool = False
    notes: str = ""
    source_url: str = ""

@dataclass
class LabelEntry:
    key: str
    text: str
    note: str
    doc_uuid: str

@dataclass
class VecResult:
    doc: Document
    chunk_text: str
    score: float
    chunk_idx: int
    char_start: int

@dataclass
class AnonYaml:
    path: Path
    generated: datetime
    docs_included: list[str]
    is_current: bool
    entities: list[dict]    # raw YAML entity list

@dataclass
class PromptItem:
    source: str             # "search" | "selection" | "tag"
    doc: Document
    chunks: list[str]       # selected chunk texts
    labels: list[LabelEntry]
    include: bool = True
```

---

## 12. Qt Signal / Slot Map

| Signal | Emitter | Connected slot |
|---|---|---|
| `set_selected(EvidenceSet)` | sidebar set list | all panels: reload for new set |
| `doc_ingested(Document)` | DocIngester worker | Docs panel: refresh list |
| `doc_indexed(str uuid)` | VecService worker | Docs panel: update "Indexed" badge |
| `anon_yaml_created(Path)` | AnonService | AnonPanel: refresh YAML history |
| `add_to_prompt(list[PromptItem])` | Search panel | Prompt Builder: append items |
| `anon_toggle_changed(bool)` | sidebar toggle | Prompt Builder: re-render preview |
| `ingestion_error(str msg)` | DocIngester worker | main window: show error dialog |

---

## 13. Key Design Decisions

**evid used as a library, not a subprocess.** Import `evid.extract`, `evid.bib` etc.
directly. The Qt app IS the evid GUI — there is no need to shell out.

**did used as a library, not a subprocess.** Same rationale. Import
`did.extract.run_extract`, `did.pseudo.pseudonymize` from the installed `did` package.
If the `did` API is not yet clean enough to import, wrap the CLI calls behind
`AnonService` so the internals can be swapped later.

**One ChromaDB client per set, opened lazily.** ChromaDB's `PersistentClient` holds a
file lock. Open it on first access, cache it in `VecService`, and close it when the set
is deselected or the app exits. This prevents lock conflicts if the user opens two sets.

**YAML history is append-only.** `did extract` runs always create a new file with a
timestamp prefix. The entity editor can modify the YAML on disk, but this is clearly
a "manual edit" to the specific file — not a new run. This gives a full audit trail.

**Anonymization is never applied to stored files.** The `original.pdf` and `.typ` files
are always the original content. Pseudonymization is applied only at export time in
memory. This keeps the tool reversible at all times.

**No SQLite app database.** All state lives in YAML/JSON files on disk, consistent with
the evid and did conventions. This makes the sets directly inspectable and portable —
the user can version-control a set folder in git.

**Tag chips as comma-separated strings in ChromaDB metadata.** ChromaDB's `where`
filter does not support array contains. Tags are stored as `"police,incident,primary"`.
Tag filtering is done client-side after the vector query, or via a pre-filter that loads
matching doc UUIDs from `info.yml` files before querying Chroma.

---

## 14. Implementation Order

1. **SetManager + basic Docs panel** — create sets, add PDFs, write info.yml, list docs.
   No vector search, no anon. Validates the evid pipeline still works as a library.

2. **VecService** — index on ingest, simple vector search panel. Validates chromadb
   per-set layout.

3. **Prompt Builder (selection mode only)** — paste selected docs into a template,
   copy to clipboard. No anonymization yet.

4. **AnonService + Anonymize panel** — YAML generation, entity editing, current YAML
   concept, Anon toggle wired to prompt export.

5. **Full Search panel** — meta filter + vector filter combined, feed to prompt builder.

6. **Export panel** — BibTeX export, anonymized/raw text export, prompt templates saved
   to disk.

7. **Polish** — drag-and-drop ingestion, document viewer with highlight, tag chip UI,
   diff view for YAML versions.
