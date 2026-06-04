"""Full file programmatic example of extraction and pseudonymization."""

import io
import sys
from pathlib import Path

from ruamel import yaml

from did.core.anonymizer import Anonymizer
from did.utils.file_utils import anonymize_file, export_to_typst, extract_text

# Ensure temp directory exists
temp_dir = Path("examples/__temp")
temp_dir.mkdir(parents=True, exist_ok=True)

# Path to the test document
input_file = Path("examples/test_document.md")

# Create Anonymizer
anonymizer = Anonymizer(language="en")

# Extract text from the file
if input_file.exists():
    text = extract_text(input_file)
else:
    sys.exit(1)

# Detect entities in the extracted text
anonymizer.detect_entities([text])

# Generate YAML config
yaml_config = anonymizer.generate_yaml()

# Load replacements from the generated config
yaml_obj = yaml.YAML()
config_data = yaml_obj.load(io.StringIO(yaml_config))
anonymizer.load_replacements(config_data)

# Anonymize the text
anonymized_text, counts = anonymizer.anonymize(text)
for value in counts.values():
    if value > 0:
        pass

# Example with file anonymization
output_file = temp_dir / "output.md"
counts = anonymize_file(input_file, anonymizer, output_file)
for value in counts.values():
    if value > 0:
        pass

# Typst export
main_path = temp_dir / "test_document.typ"
export_to_typst(input_file, anonymizer, main_path)
