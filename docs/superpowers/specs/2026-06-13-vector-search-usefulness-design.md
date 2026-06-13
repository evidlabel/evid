# Vector search usefulness — design

Date: 2026-06-13
Status: approved (design); pending implementation

## Problem

In the GUI Search tab → Vector search, the right-hand preview pane is
uninformative. A query surfaces results whose matched chunk is a single
word (e.g. `Rammerne`), and the preview shows only that bare chunk plus a
junk auto-title label (`Microsoft Word - tmp2pdf1933727`). The user cannot
tell why a result matched or what the surrounding passage says.

Root cause: chunking splits indexed text on blank lines
(`text.split("\n\n")`), so a Typst section heading on its own line becomes
its own one-word chunk. That chunk gets embedded and can surface as a top
hit with no context. The preview then renders only `res.chunk_text`.

This logic is **duplicated**: `evid/services/vec_service.py` `_chunk` /
`_char_starts`, and `evid/vec/safe_index.py` `_index_worker` (the
subprocess path the GUI actually uses via `index_document_isolated`). They
must stay in sync.

Out of scope (explicitly declined): rewriting junk auto-title labels.

## Goals

1. Stop one-word/heading-only chunks from being indexed and surfaced.
2. Make the preview readable: show context around the match, highlighted.
3. Make the similarity score legible.

## Design

### 1. Shared chunking with small-fragment merging

Create a single module `evid/vec/chunking.py`:

```python
MIN_CHARS = 80  # fragments shorter than this are merged into a neighbor

def chunk_text(text: str) -> list[tuple[str, int]]:
    """Split on blank lines, then merge short fragments into a neighbor.

    Returns a list of (chunk, char_start) where char_start is the offset of
    the chunk's first character in the original *text*.
    """
```

Algorithm:
- Split `text` on `\n\n`, strip, drop empties — as today — but track each
  fragment's `char_start` in the original text (via `text.find(frag, pos)`,
  same pointer-advancing scan already used).
- Walk the fragments left to right. If a fragment's length `< MIN_CHARS`,
  append it to the **previous** accumulated chunk (joined with a single
  space or newline). If there is no previous chunk yet (leading short
  fragment, e.g. a heading), hold it and prepend it to the **next** chunk.
- A merged chunk's `char_start` is the offset of its first constituent
  fragment, so it still points into the original text correctly.
- Edge case: a document that is entirely short fragments collapses to a
  single chunk. A single fragment ≥ MIN_CHARS passes through unchanged.

Both `vec_service.py` and `safe_index.py` import and call `chunk_text`,
replacing their inline `split("\n\n")` + `_char_starts` code. `char_start`
metadata semantics are unchanged, so existing query/preview code keeps
working.

`MIN_CHARS = 80` ≈ one line of prose — confirmed with user.

**Reindex required.** Old chunks already in ChromaDB are not rewritten by
this change. There is currently no standalone reindex CLI command; indexing
runs on `evid <set> add` or programmatically via
`DocIngester.index_existing(doc_dir, evidence_set)`. To refresh an existing
set (e.g. `litc`) after this change, iterate its `docs/*/` dirs and call
`index_existing` on each (it deletes the doc's old chunks before re-adding).
Adding a thin `set reindex` CLI/GUI affordance is a reasonable follow-up but
is **not** part of this spec's required scope; the implementation plan may
include a one-off reindex helper to validate the change end to end.

### 2. Preview shows surrounding context, highlighted

In `evid/gui/tabs/search_tab.py` `_update_preview`, for a `VecResult`:
- Read the doc's `label.typ` (`evidence_set.path / "docs" / uuid /
  "label.typ"`).
- Take a window of `±CONTEXT_CHARS` (default 600) around `res.char_start`,
  clamped to text bounds. Prepend/append `…` when clipped.
- Render into the `QTextEdit` as rich text: the matched chunk span
  (`char_start … char_start + len(chunk_text)`) shown **bold/highlighted**,
  surrounding context in normal weight.
- Fallbacks: if `label.typ` is missing/empty or `char_start` can't be
  located, fall back to the current plain `res.chunk_text`, then to
  `_citations_preview(uuid)` (unchanged).

Meta-search results (no `VecResult`) keep their current
`_citations_preview` behavior — only the vector branch changes.

### 3. Score clarity

The displayed score is cosine similarity. ChromaDB returns cosine
*distance* `= 1 − cos`; the code computes `score = 1.0 − distance = cos`,
range −1…1. Negative values mean "weakly related," not an error.

Changes (display only, no algorithm change):
- Rename results column header `Score` → `Similarity` (`_RESULT_COLS`).
- Tooltip on the column header and on the preview score label:
  *"Cosine similarity, −1…1. Higher = more relevant."*

## Components / files touched

- `evid/vec/chunking.py` — **new**: `chunk_text`, `MIN_CHARS`.
- `evid/services/vec_service.py` — use `chunk_text`; drop `_chunk`/`_char_starts`.
- `evid/vec/safe_index.py` — use `chunk_text` in `_index_worker`.
- `evid/gui/tabs/search_tab.py` — context-window highlighted preview;
  header rename + tooltips.

## Testing

- `chunk_text` unit tests: heading-then-paragraph merges into one chunk;
  leading short fragment prepends to next; trailing short fragment appends
  to previous; all-short collapses to one; long paragraph passes through;
  `char_start` offsets point at the right place in the original text;
  reconstructed chunks preserve original substrings for `find`-based
  char_start to remain valid.
- Verify `vec_service` and `safe_index` produce identical chunk lists for
  the same input (guard against re-divergence).
- GUI: existing search-tab tests still pass; add a test that a `VecResult`
  with a short `chunk_text` yields a preview longer than the chunk when
  `label.typ` provides context, and that the matched span is highlighted.

## Error handling

- Preview file read wrapped so a missing/unreadable `label.typ` degrades to
  the plain-chunk fallback rather than raising (per project rule: surface to
  logger, never crash the Qt slot).
