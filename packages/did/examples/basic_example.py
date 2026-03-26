"""Basic programmatic example of extraction and pseudonymization."""

from did.core.anonymizer import Anonymizer
import io
import ruamel.yaml as yaml

# Sample text
sample_text = """Hello John Doe, how are you? Contact Jane Smith at 1234567890 or email john.doe@example.com."""

# Create Anonymizer
anonymizer = Anonymizer(language="en")

# Detect entities in the sample text
anonymizer.detect_entities([sample_text])

# Generate YAML config
yaml_config = anonymizer.generate_yaml()
print("Generated YAML config:")
print(yaml_config)

# Load replacements from the generated config
yaml_obj = yaml.YAML()
config_data = yaml_obj.load(io.StringIO(yaml_config))
anonymizer.load_replacements(config_data)

# Anonymize the text
anonymized_text, counts = anonymizer.anonymize(sample_text)
print("\nAnonymized text:")
print(anonymized_text)
print("\nReplacement counts:")
for key, value in counts.items():
    if value > 0:
        print(f"  {key}: {value}")
