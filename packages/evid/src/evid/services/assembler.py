"""Recipe-based prompt assembler — no Qt imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ── data structures ───────────────────────────────────────────────────────────


@dataclass
class Section:
    layer_id: str
    kind: str  # "evidence" | "grounding" | "final_question"
    text: str  # formatted markdown text for this section
    anchor: str  # first line of text; used for scroll targeting
    doc_count: int = 0


@dataclass
class AssembledPrompt:
    full_text: str
    sections: list[Section]
    warnings: list[str]


@dataclass
class RecipeLayer:
    layer_id: str
    evidence_tokens: list[str]
    grounding_path: Path | None  # resolved absolute path, or None
    grounding_rel: str  # original string from YAML (empty if absent)
    children: list[RecipeLayer] = field(default_factory=list)


# ── public API ────────────────────────────────────────────────────────────────


def parse_recipe(
    recipe_path: str,
) -> tuple[list[RecipeLayer], str | None, list[str]]:
    """Parse recipe YAML and return (layers, final_question_rel, warnings).

    Does NOT touch corpus_index — pure structural parsing.
    """
    warnings: list[str] = []
    recipe_dir = Path(recipe_path).parent
    try:
        with open(recipe_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        return [], None, [f"Failed to read recipe: {exc}"]

    raw_layers = data.get("layers", [])
    layers = _parse_layer_list(raw_layers, recipe_dir, warnings)
    final_question_rel: str | None = data.get("final_question")
    return layers, final_question_rel, warnings


def list_grounding_files(recipe_path: str) -> list[str]:
    """Return absolute paths of all grounding files that exist on disk."""
    layers, final_question_rel, _ = parse_recipe(recipe_path)
    recipe_dir = Path(recipe_path).parent
    result: list[str] = []

    def _collect(ls: list[RecipeLayer]) -> None:
        for layer in ls:
            if layer.grounding_path and layer.grounding_path.exists():
                result.append(str(layer.grounding_path))
            _collect(layer.children)

    _collect(layers)
    if final_question_rel:
        fq_path = (recipe_dir / final_question_rel).resolve()
        if fq_path.exists():
            result.append(str(fq_path))
    return result


def assemble(
    recipe_path: str,
    corpus_index: dict[str, list[str]],
) -> AssembledPrompt:
    """Assemble the full prompt from recipe + corpus_index (depth-first, pre-order)."""
    layers, final_question_rel, warnings = parse_recipe(recipe_path)
    recipe_dir = Path(recipe_path).parent
    sections: list[Section] = []

    _walk_layers(layers, corpus_index, recipe_dir, sections, warnings)

    if final_question_rel:
        fq_path = (recipe_dir / final_question_rel).resolve()
        anchor = "### [final_question] ###"
        if fq_path.exists():
            fq_text = fq_path.read_text(encoding="utf-8").strip()
            text = f"{anchor}\n\n{fq_text}"
        else:
            warnings.append(f"Final question file not found: {final_question_rel}")
            text = f"{anchor}\n\n<!-- final_question missing: {final_question_rel} -->"
        sections.append(Section("final_question", "final_question", text, anchor))

    full_text = "\n\n".join(s.text for s in sections)
    return AssembledPrompt(full_text, sections, warnings)


def assemble_subtree(
    recipe_path: str,
    layer_id: str,
    corpus_index: dict[str, list[str]],
) -> AssembledPrompt:
    """Assemble ancestors of target layer + target layer itself.

    Excludes siblings, children of target, and final_question.
    """
    layers, _fq, warnings = parse_recipe(recipe_path)
    recipe_dir = Path(recipe_path).parent
    path = _find_ancestor_path(layers, layer_id)
    if path is None:
        return AssembledPrompt("", [], [f"Layer '{layer_id}' not found in recipe"])

    sections: list[Section] = []
    for layer in path:
        sections.extend(
            _assemble_single_layer(layer, corpus_index, recipe_dir, warnings)
        )

    full_text = "\n\n".join(s.text for s in sections)
    return AssembledPrompt(full_text, sections, warnings)


# ── internal helpers ──────────────────────────────────────────────────────────


def _parse_layer_list(
    raw: list,
    recipe_dir: Path,
    warnings: list[str],
) -> list[RecipeLayer]:
    result = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        layer_id = str(item.get("id", "unnamed"))
        evidence_tokens = [str(t) for t in (item.get("evidence") or [])]
        grounding_rel = item.get("grounding", "") or ""
        if grounding_rel:
            grounding_path: Path | None = (recipe_dir / grounding_rel).resolve()
        else:
            grounding_path = None
        children = _parse_layer_list(item.get("layers", []), recipe_dir, warnings)
        result.append(
            RecipeLayer(
                layer_id=layer_id,
                evidence_tokens=evidence_tokens,
                grounding_path=grounding_path,
                grounding_rel=grounding_rel,
                children=children,
            )
        )
    return result


def _walk_layers(
    layers: list[RecipeLayer],
    corpus_index: dict[str, list[str]],
    recipe_dir: Path,
    sections: list[Section],
    warnings: list[str],
) -> None:
    for layer in layers:
        sections.extend(
            _assemble_single_layer(layer, corpus_index, recipe_dir, warnings)
        )
        _walk_layers(layer.children, corpus_index, recipe_dir, sections, warnings)


def _assemble_single_layer(
    layer: RecipeLayer,
    corpus_index: dict[str, list[str]],
    recipe_dir: Path,
    warnings: list[str],
) -> list[Section]:
    sections: list[Section] = []

    # ── evidence section ──────────────────────────────────────────────────────
    doc_texts = _resolve_evidence(layer.evidence_tokens, corpus_index, warnings)
    tokens_joined = (
        ", ".join(layer.evidence_tokens) if layer.evidence_tokens else "(none)"
    )
    anchor_ev = (
        f"### [{layer.layer_id}] evidence: {tokens_joined} ({len(doc_texts)} docs) ###"
    )
    ev_parts = [anchor_ev]
    for doc_text in doc_texts:
        ev_parts.append(doc_text.strip())
    ev_text = "\n\n".join(ev_parts)
    sections.append(
        Section(layer.layer_id, "evidence", ev_text, anchor_ev, len(doc_texts))
    )

    # ── grounding section ─────────────────────────────────────────────────────
    if layer.grounding_rel:
        filename = Path(layer.grounding_rel).name
        anchor_gr = f"### [{layer.layer_id}] grounding: {filename} ###"
        if layer.grounding_path and layer.grounding_path.exists():
            gr_text = layer.grounding_path.read_text(encoding="utf-8").strip()
            text = f"{anchor_gr}\n\n{gr_text}"
        else:
            warnings.append(
                f"Grounding file not found for layer '{layer.layer_id}': {layer.grounding_rel}"
            )
            text = f"{anchor_gr}\n\n<!-- grounding missing: {layer.grounding_rel} -->"
        sections.append(Section(layer.layer_id, "grounding", text, anchor_gr))

    return sections


def _resolve_evidence(
    tokens: list[str],
    corpus_index: dict[str, list[str]],
    warnings: list[str],
) -> list[str]:
    results: list[str] = []
    seen: set[int] = set()

    for token in tokens:
        if token.startswith("evid-"):
            uuid_key = token[5:]
            texts = corpus_index.get(uuid_key)
            if texts is None:
                warnings.append(f"Unresolved UUID token '{token}'")
                continue
            candidates = texts
        else:
            candidates = corpus_index.get(token, [])
            if not candidates:
                warnings.append(f"Tag '{token}' matched 0 docs")
                results.append(f"<!-- tag '{token}' matched 0 docs -->")
                continue

        for text in candidates:
            id(text) if isinstance(text, str) else hash(text)
            # Deduplicate by content hash
            h = hash(text)
            if h not in seen:
                seen.add(h)
                results.append(text)

    return results


def _find_ancestor_path(
    layers: list[RecipeLayer],
    target_id: str,
    current_path: list[RecipeLayer] | None = None,
) -> list[RecipeLayer] | None:
    if current_path is None:
        current_path = []
    for layer in layers:
        new_path = [*current_path, layer]
        if layer.layer_id == target_id:
            return new_path
        result = _find_ancestor_path(layer.children, target_id, new_path)
        if result is not None:
            return result
    return None
