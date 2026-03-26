"""Full file programmatic example of extraction and pseudonymization."""

from pathlib import Path
from did.core.anonymizer import Anonymizer
from did.utils.file_utils import extract_text, anonymize_file, export_to_typst
import io
import ruamel.yaml as yaml

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
    print(f"File {input_file} not found.")
    exit(1)

# Detect entities in the extracted text
anonymizer.detect_entities([text])

# Generate YAML config
yaml_config = anonymizer.generate_yaml()
print("Generated YAML config:")
print(yaml_config)

# Load replacements from the generated config
yaml_obj = yaml.YAML()
config_data = yaml_obj.load(io.StringIO(yaml_config))
anonymizer.load_replacements(config_data)

# Anonymize the text
anonymized_text, counts = anonymizer.anonymize(text)
print("\nAnonymized text:")
print(anonymized_text)
print("\nReplacement counts:")
for key, value in counts.items():
    if value > 0:
        print(f"  {key}: {value}")

# Example with file anonymization
output_file = temp_dir / "output.md"
counts = anonymize_file(input_file, anonymizer, output_file)
print(f"\nFile anonymized to {output_file}")
print("File replacement counts:")
for key, value in counts.items():
    if value > 0:
        print(f"  {key}: {value}")

# Typst export
main_path = temp_dir / "test_document.typ"
export_to_typst(input_file, anonymizer, main_path)
print(f"\nTypst files written to {main_path.parent}")
print(f" - {main_path}")
print(f" - {main_path.parent / f'{main_path.stem}_vars.typ'}")
print(f" - {main_path.parent / f'{main_path.stem}_fakevars.typ'}")
