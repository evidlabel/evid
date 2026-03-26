"""AnonService — entity extraction and pseudonymisation wrapping did."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evidmgr.models import AnonMode, AnonYaml, EvidenceSet

logger = logging.getLogger(__name__)

# Entity type → placeholder prefix mapping
_PLACEHOLDER_PREFIXES = {
    "PERSON": "PERSON",
    "EMAIL_ADDRESS": "EMAIL",
    "LOCATION": "ADDRESS",
    "PHONE_NUMBER": "PHONE",
    "ID_NUMBER": "ID",
    "CODE_NUMBER": "CODE",
    "GENERAL_NUMBER": "NUMBER",
    "DATE_NUMBER": "DATE",
    "URL": "URL",
}


class AnonService:
    """Manages anon/ YAML history and applies pseudonymisation for a set."""

    # ── extraction ─────────────────────────────────────────────────────────────

    def run_extract(
        self,
        evidence_set: "EvidenceSet",
        doc_uuids: list[str],
        language: str | None = None,
    ) -> Path:
        """Run did entity extraction on the given docs and save a new YAML."""
        lang = language or evidence_set.anon_language

        # Collect .typ texts
        texts: list[str] = []
        for uuid in doc_uuids:
            typ_files = list((evidence_set.path / "docs" / uuid).glob("*.typ"))
            if typ_files:
                try:
                    texts.append(typ_files[0].read_text(encoding="utf-8"))
                except Exception:
                    logger.exception("Could not read .typ for %s", uuid)

        if not texts:
            msg = "No .typ files found for the given UUIDs"
            raise ValueError(msg)

        # Run did extraction (lazy import — presidio/spaCy may be absent)
        try:
            from did.core.anonymizer import Anonymizer  # noqa: PLC0415
        except ImportError as e:
            msg = f"did package is not installed or spaCy models are missing: {e}"
            raise RuntimeError(msg) from e

        anonymizer = Anonymizer(language=lang)
        anonymizer.detect_entities(texts)
        did_yaml_str = anonymizer.generate_yaml()

        # Convert did YAML schema → evidmgr entity schema
        entities = self._did_yaml_to_entities(did_yaml_str, doc_uuids)

        # Save to anon/<ISO>_entities.yml
        anon_dir = evidence_set.path / "anon"
        anon_dir.mkdir(exist_ok=True)
        iso = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S")
        yaml_path = anon_dir / f"{iso}_entities.yml"

        import yaml  # noqa: PLC0415

        data = {
            "generated": datetime.now(tz=timezone.utc).isoformat(),
            "docs_included": doc_uuids,
            "language": lang,
            "entities": entities,
        }
        with yaml_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

        logger.info("Saved entity YAML to %s", yaml_path)
        return yaml_path

    # ── YAML management ────────────────────────────────────────────────────────

    def list_yamls(self, evidence_set: "EvidenceSet") -> list["AnonYaml"]:
        from evidmgr.models import AnonYaml  # noqa: PLC0415
        import yaml  # noqa: PLC0415

        anon_dir = evidence_set.path / "anon"
        if not anon_dir.exists():
            return []
        current_name = self._read_current(anon_dir)
        result = []
        for yml_file in sorted(anon_dir.glob("*_entities.yml"), reverse=True):
            try:
                with yml_file.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                generated = data.get("generated")
                if isinstance(generated, str):
                    generated = datetime.fromisoformat(generated)
                result.append(
                    AnonYaml(
                        path=yml_file,
                        generated=generated or datetime.now(tz=timezone.utc),
                        docs_included=data.get("docs_included", []),
                        is_current=yml_file.name == current_name,
                        entities=data.get("entities", []),
                    )
                )
            except Exception:
                logger.exception("Failed to load YAML %s", yml_file)
        return result

    def set_current(self, evidence_set: "EvidenceSet", yaml_path: Path) -> None:
        anon_dir = evidence_set.path / "anon"
        (anon_dir / "current").write_text(yaml_path.name, encoding="utf-8")

    def get_current_yaml(self, evidence_set: "EvidenceSet") -> "AnonYaml | None":
        yamls = self.list_yamls(evidence_set)
        for y in yamls:
            if y.is_current:
                return y
        return yamls[0] if yamls else None

    def save_entity_yaml(
        self, evidence_set: "EvidenceSet", yaml_path: Path, entities: list[dict]
    ) -> None:
        """Write edited entities back to an existing YAML file."""
        import yaml  # noqa: PLC0415

        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data["entities"] = entities
        with yaml_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    # ── pseudonymisation ───────────────────────────────────────────────────────

    def pseudonymize(
        self,
        text: str,
        evidence_set: "EvidenceSet",
        mode: "AnonMode",
    ) -> str:
        from evidmgr.models import AnonMode  # noqa: PLC0415

        if mode == AnonMode.REAL:
            return text

        yaml_obj = self.get_current_yaml(evidence_set)
        if yaml_obj is None:
            return text

        field = "placeholder" if mode == AnonMode.PLACEHOLDER else "fake"
        result = text
        for entity in yaml_obj.entities:
            replacement = ""
            if isinstance(entity, dict):
                replacement = (entity.get(field) or entity.get("placeholder") or "").strip()
                original = entity.get("original", "")
                variants = entity.get("variants", [])
            else:
                replacement = (getattr(entity, field, None) or entity.placeholder or "").strip()
                original = entity.original
                variants = entity.variants

            if not replacement:
                continue
            for term in [original, *variants]:
                if term:
                    result = result.replace(term, replacement)
        return result

    def generate_fakes(self, yaml_path: Path, language: str = "da") -> None:
        """Populate the `fake` column in a YAML using faker and name_lookup."""
        import yaml  # noqa: PLC0415
        from faker import Faker  # noqa: PLC0415

        locale = "da_DK" if language == "da" else "en_US"
        fake = Faker(locale)

        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        entities = data.get("entities", [])
        for entity in entities:
            if entity.get("fake"):
                continue  # Don't overwrite existing fakes
            etype = entity.get("entity_type", "")
            if etype == "PERSON":
                entity["fake"] = fake.name()
            elif etype in {"LOCATION", "ADDRESS"}:
                entity["fake"] = fake.address().replace("\n", ", ")
            elif etype in {"ID_NUMBER", "CODE_NUMBER"}:
                entity["fake"] = fake.numerify(text="######-####")
            elif etype == "PHONE_NUMBER":
                entity["fake"] = fake.phone_number()
            elif etype == "EMAIL_ADDRESS":
                entity["fake"] = fake.email()
            else:
                entity["fake"] = entity.get("placeholder", "")

        with yaml_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    # ── internal ───────────────────────────────────────────────────────────────

    @staticmethod
    def _read_current(anon_dir: Path) -> str:
        current_file = anon_dir / "current"
        if current_file.exists():
            return current_file.read_text(encoding="utf-8").strip()
        return ""

    @staticmethod
    def _did_yaml_to_entities(did_yaml_str: str, doc_uuids: list[str]) -> list[dict]:
        """Convert did's detection YAML to evidmgr entity list with placeholder column."""
        import yaml  # noqa: PLC0415

        data = yaml.safe_load(did_yaml_str) or {}
        entities = []
        counters: dict[str, int] = {}

        for entity_type, items in data.items():
            if not isinstance(items, list):
                continue
            prefix = _PLACEHOLDER_PREFIXES.get(entity_type, entity_type)
            for item in items:
                if not isinstance(item, dict):
                    continue
                original = item.get("id", "")
                variants = item.get("variants", [])
                counters[prefix] = counters.get(prefix, 0) + 1
                n = counters[prefix]
                label_str = f"{prefix} {chr(64 + n)}" if n <= 26 else f"{prefix} {n}"
                placeholder = f"[{label_str}]"
                entities.append(
                    {
                        "original": original,
                        "variants": variants,
                        "entity_type": entity_type,
                        "placeholder": placeholder,
                        "fake": "",
                    }
                )
        return entities
