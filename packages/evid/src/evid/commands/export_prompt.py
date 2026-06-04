"""Export a recipe YAML to a Hugo prompt builder JSON."""

import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from .models_prompt import Layer, QuestioningLine, Recipe

logger = logging.getLogger(__name__)


def is_uuid(ref: str) -> bool:
    clean = ref.replace("-", "")
    return len(clean) == 32 and re.fullmatch(r"[0-9a-fA-F]+", clean) is not None


def resolve_ref(ref: str, evid_api) -> list[str]:
    """
    Resolve one evidence reference to an ordered list of UUIDs.

    evid_api must provide:
      resolve_tag(tag: str, namespace: str | None = None) -> List[str]
      resolve_alias(alias: str) -> str | None
      resolve_uuid(uuid: str) -> tuple[str, str]  # (name, text)
    """
    if is_uuid(ref):
        return [ref.replace("-", "")]
    if "." in ref:
        namespace, tag = ref.split(".", 1)
        return evid_api.resolve_tag(tag, namespace=namespace)
    alias = evid_api.resolve_alias(ref)
    if alias:
        return [alias]
    return evid_api.resolve_tag(ref)


def resolve_evidence(refs: list[str], evid_api) -> list[str]:
    """Expand a list of refs to an ordered, deduplicated list of UUIDs."""
    seen, result = set(), []
    for ref in refs:
        for uuid in resolve_ref(ref, evid_api):
            if uuid not in seen:
                seen.add(uuid)
                result.append(uuid)
    return result


def _build_layer(layer: Layer, recipe_dir: Path, evid_api) -> dict[str, Any]:
    uuids = resolve_evidence(layer.evidence, evid_api)
    sources = {}
    for uuid in uuids:
        try:
            name, url, snippets = evid_api.resolve_uuid(uuid)
            sources[uuid] = {
                "name": name,
                "url": url,
                "snippets": snippets,
            }
        except Exception as e:
            logger.warning("Could not resolve UUID %s: %s", uuid, e)

    grounding = ""
    if layer.grounding:
        gpath = recipe_dir / layer.grounding
        if gpath.exists():
            grounding = gpath.read_text(encoding="utf-8")
        else:
            logger.warning("Grounding not found: %s", gpath)

    return {
        "id": layer.id,
        "title": layer.title or layer.id,
        "grounding": grounding,
        "sources": sources,
        "active": uuids,
    }


def _build_questioning(q: QuestioningLine, recipe_dir: Path) -> dict[str, Any]:
    text = ""
    if q.body:
        text = q.body
    elif q.file:
        fpath = (recipe_dir / q.file).resolve()
        if fpath.exists():
            text = fpath.read_text(encoding="utf-8")
        else:
            logger.warning("Questioning file not found: %s", fpath)
    return {"id": q.id, "name": q.name, "text": text}


def _norm_guide_item(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "label": item.label,
        "add_layers": item.add_layers,
        "add_questioning": item.add_questioning,
        "children": [
            {
                "id": c.id,
                "label": c.label,
                "add_layers": c.add_layers,
                "add_questioning": c.add_questioning,
                "children": [],
            }
            for c in item.children
        ],
    }


def export_prompt(
    recipe_path: Path,
    output_path: Path,
    evid_api,
    title_override: str | None = None,
    filename_override: str | None = None,
) -> None:
    """Compile a recipe YAML into a self-contained Hugo prompt JSON."""
    recipe_dir = recipe_path.parent

    with open(recipe_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    recipe = Recipe(**raw)

    title = title_override or recipe.title
    output_filename = (
        filename_override or recipe.output_filename or (output_path.stem + ".md")
    )

    layers = [_build_layer(layer, recipe_dir, evid_api) for layer in recipe.layers]
    questioning = [_build_questioning(q, recipe_dir) for q in recipe.questioning]

    result = {
        "id": recipe.id,
        "title": title,
        "output_filename": output_filename,
        "recipe": True,
        "guide": [_norm_guide_item(i) for i in recipe.guide],
        "layers": layers,
        "questioning": questioning,
        "default_questioning": recipe.default_questioning,
        "final_question": recipe.final_question or "",
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    logger.info("Exported %r → %s", title, output_path)


def _render_evidence_markdown(layers: list[dict[str, Any]]) -> str:
    parts = []
    for layer in layers:
        parts.append(f"## {layer['title']}\n")
        if layer["grounding"]:
            parts.append(layer["grounding"].strip() + "\n")
        for uuid in layer["active"]:
            opt = layer["sources"].get(uuid, {})
            name = opt.get("name", uuid)
            text = "\n\n".join(s["text"] for s in opt.get("snippets", [])).strip()
            parts.append(f"### {name}\n\n{text}\n")
    return "\n".join(parts)


def export_markdown(
    recipe_path: Path,
    output_path: Path,
    evid_api,
) -> None:
    """Compile a recipe YAML into a Markdown prompt document."""
    recipe_dir = recipe_path.parent

    with open(recipe_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    recipe = Recipe(**raw)

    layers = [_build_layer(layer, recipe_dir, evid_api) for layer in recipe.layers]

    lines = [f"# {recipe.title}\n"]
    lines.append(_render_evidence_markdown(layers))
    if recipe.final_question:
        lines.append(f"\n---\n\n{recipe.final_question}\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Exported %r → %s (markdown)", recipe.title, output_path)


def export_typst(
    recipe_path: Path,
    output_path: Path,
    evid_api,
) -> None:
    """Compile a recipe YAML into a Typst prompt document."""
    recipe_dir = recipe_path.parent

    with open(recipe_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    recipe = Recipe(**raw)

    layers = [_build_layer(layer, recipe_dir, evid_api) for layer in recipe.layers]

    lines = [f"= {recipe.title}\n"]
    for layer in layers:
        lines.append(f"== {layer['title']}\n")
        if layer["grounding"]:
            lines.append(layer["grounding"].strip() + "\n")
        for uuid in layer["active"]:
            opt = layer["sources"].get(uuid, {})
            name = opt.get("name", uuid)
            text = "\n\n".join(s["text"] for s in opt.get("snippets", [])).strip()
            lines.append(f"=== {name}\n\n{text}\n")
    if recipe.final_question:
        lines.append(f"\n---\n\n{recipe.final_question}\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Exported %r → %s (typst)", recipe.title, output_path)


# ── EvIdAPI ────────────────────────────────────────────────────────────────────


class EvIdAPI:
    """Thin adapter over evid.core.Database for evidence resolution."""

    def __init__(self, db_path: Path):
        from evid.core.database import Database

        self._db_path = db_path
        self._db = Database(db_path)

    def resolve_uuid(self, uuid: str) -> tuple[str, str, list]:
        """Return (title, url, snippets) for a UUID.

        snippets is a list of {page, text} dicts from label.json.
        If the same UUID appears in multiple datasets, prefer the first copy
        that has non-empty snippets.
        """
        first: tuple[str, str] | None = None
        for dataset, entries in self._db.db.items():
            for entry in entries.values():
                if entry.get("uuid") == uuid:
                    name = entry.get("title", uuid)
                    url = entry.get("url", "")
                    workdir = (
                        Path(entry["_workdir"])
                        if "_workdir" in entry
                        else self._db_path / dataset / uuid
                    )
                    snippets = self._load_snippets(workdir)
                    if snippets:
                        return name, url, snippets
                    if first is None:
                        first = (name, url)
        if first is not None:
            return first[0], first[1], []
        raise KeyError(f"UUID not found: {uuid}")

    def _load_snippets(self, workdir: Path) -> list:
        """Return [{page, text}] from label.json, skipping the 'main' entry."""
        json_file = workdir / "label.json"
        if not json_file.exists():
            return []
        with json_file.open(encoding="utf-8") as f:
            data = json.load(f)
        snippets = []
        for item in data:
            val = item.get("value", {})
            if val.get("key") == "main":
                continue
            text = val.get("note") or val.get("text", "")
            if text:
                snippets.append(
                    {"page": val.get("page") or val.get("opage"), "text": text}
                )
        return snippets

    def resolve_tag(self, tag: str, namespace: str | None = None) -> list[str]:
        """Return UUIDs whose tags field contains the given tag."""
        full_tag = f"{namespace}.{tag}" if namespace else tag
        results = []
        for entries in self._db.db.values():
            for entry in entries.values():
                tags = [
                    t.strip() for t in (entry.get("tags") or "").split(",") if t.strip()
                ]
                if full_tag in tags or (namespace and tag in tags):
                    results.append(entry["uuid"])
        return results

    def resolve_alias(self, alias: str) -> str | None:
        """Return a UUID whose label field matches the alias."""
        for entries in self._db.db.values():
            for entry in entries.values():
                if entry.get("label") == alias:
                    return entry["uuid"]
        return None


def get_evid_api(db_path: Path) -> EvIdAPI:
    return EvIdAPI(db_path)
