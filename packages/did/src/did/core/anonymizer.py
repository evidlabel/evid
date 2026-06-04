"""Main Anonymizer class."""

from presidio_analyzer import (
    AnalyzerEngine,
    RecognizerRegistry,
)
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import EmailRecognizer

from .config import generate_yaml, load_replacements
from .detection import detect_entities, preprocess_text
from .models import Config
from .recognizers import get_custom_recognizers
from .replacement import anonymize


class Anonymizer:
    """Handles entity detection and anonymization."""

    def __init__(self, language="en"):
        conf = {
            "nlp_engine_name": "spacy",
            "models": [
                {"lang_code": "da", "model_name": "da_core_news_lg"},
                {"lang_code": "en", "model_name": "en_core_web_md"},
            ],
            "ner_model_configuration": {
                "model_to_presidio_entity_mapping": {
                    "PER": "PERSON",
                    "GPE": "LOCATION",
                    "ORG": "ORGANIZATION",
                    "MISC": "NRP",
                },
                "labels_to_ignore": ["O"],
            },
        }

        try:
            nlp_engine = NlpEngineProvider(nlp_configuration=conf).create_engine()
        except Exception as e:
            msg = f"NLP engine could not be created for language '{language}': {e}"
            raise ValueError(msg)

        registry = RecognizerRegistry(supported_languages=[language, "en"])
        registry.load_predefined_recognizers(languages=[language, "en"])
        registry.add_recognizer(EmailRecognizer(supported_language=language))
        for custom_recognizer in get_custom_recognizers(language):
            registry.add_recognizer(custom_recognizer)

        self.analyzer = AnalyzerEngine(
            registry=registry,
            nlp_engine=nlp_engine,
            supported_languages=[language, "en"],
        )

        self.counts = {
            "person_found": 0,
            "person_replaced": 0,
            "email_address_found": 0,
            "email_address_replaced": 0,
            "location_found": 0,
            "location_replaced": 0,
            "phone_number_found": 0,
            "phone_number_replaced": 0,
            "date_number_found": 0,
            "date_number_replaced": 0,
            "id_number_found": 0,
            "id_number_replaced": 0,
            "code_number_found": 0,
            "code_number_replaced": 0,
            "general_number_found": 0,
            "general_number_replaced": 0,
            "url_found": 0,
            "url_replaced": 0,
        }
        self.entities: Config = Config()
        self.language = language
        self.model_map = {"en": "en_core_web_md", "da": "da_core_news_lg"}

    def detect_entities(self, texts: list):
        """Detect entities in multiple texts using Presidio."""
        detect_entities(self, texts)

    def generate_yaml(self) -> str:
        """Generate YAML configuration from detected entities with all strings quoted."""
        return generate_yaml(self)

    def load_replacements(self, config: dict):
        """Load replacements from YAML config using explicit mapping for robustness."""
        load_replacements(self, config)

    def anonymize(self, text: str) -> tuple:
        """Anonymize text by replacing known variants with Typst-style parameters in a single pass."""
        return anonymize(self, text)

    def preprocess_text(self, text: str):
        """Preprocess text to join hyphenated multi-line words for detection."""
        return preprocess_text(text)
