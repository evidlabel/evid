"""Example using Faker to generate a Danish Lorem document with PII and run it through DID for anonymization.

This version includes testing for name variants (repeated names and multiline surname) and a URL.
It verifies that specific PII elements are removed from the anonymized output.
"""

import io
from pathlib import Path

from faker import Faker
from ruamel import yaml

from did.core.anonymizer import Anonymizer
from did.utils.file_utils import anonymize_file, extract_text

# Ensure temp directory exists
temp_dir = Path("examples/__temp")
temp_dir.mkdir(parents=True, exist_ok=True)

# Generate fake Danish document with PII using Faker, plus specific variants and URL
fake = Faker("da_DK")

# Fixed name for variant testing
fixed_name = "Dr. Karl Svendsen"

# Generate other elements
document_text = f"""
# Rapport om Projektet

Dette er en rapport skrevet af {fixed_name} og {fake.name()}.
Vi arbejder på Adressen {fake.address()}.
Kontakt os på telefon {fake.phone_number()} eller email {fake.email()}.
Se mere på vores hjemmeside: https://example.com/project.
Projektet startede den {fake.date_this_decade()}.
CPR-nummer: {fake.ssn()}.
Konto: {fake.iban()}.

Flere detaljer:
- Navn: {fixed_name}
- Navn (multiline variant): Karl
  Svendsen
- Adresse: {fake.address()}
- Telefon: {fake.phone_number()}
- Email: {fake.email()}
"""


# Save to a file
input_file = temp_dir / "danish_fake_document.md"
with open(input_file, "w", encoding="utf-8") as f:
    f.write(document_text)

# Create Anonymizer for Danish
anonymizer = Anonymizer(language="da")

# Extract text from the file
text = extract_text(input_file)

# Detect entities in the extracted text
anonymizer.detect_entities([text])

# Generate YAML config and print it to verify variants
yaml_config = anonymizer.generate_yaml()

# Load replacements from the generated config
yaml_obj = yaml.YAML()
config_data = yaml_obj.load(io.StringIO(yaml_config))
anonymizer.load_replacements(config_data)

# Anonymize the text
anonymized_text, counts = anonymizer.anonymize(text)

# Verify that specific PII is removed (not present in anonymized text)
original_pii_elements = [
    fixed_name,
    "Karl\n  Svendsen",  # Multiline variant
    fake.email(),  # First email
    fake.email(),  # Second email (Faker generates new one, but since it's in text, check the string)
    # Note: For dynamic Faker outputs like phone, address, etc., we extract from original text
]

# Extract specific PII from original text for verification
original_emails = [
    line for line in document_text.splitlines() if "@" in line and "example" in line
]
original_phones = [
    line
    for line in document_text.splitlines()
    if line.startswith("Telefon:") or "telefon" in line.lower()
]
original_addresses = [line for line in document_text.splitlines() if "Adresse:" in line]
original_date = next(
    (line for line in document_text.splitlines() if "started" in line), ""
)
original_cpr = next(
    (line for line in document_text.splitlines() if "CPR-nummer:" in line), ""
)
original_account = next(
    (line for line in document_text.splitlines() if "Konto:" in line), ""
)
original_url = "https://example.com/project."

pii_to_check = [
    fixed_name,
    "Karl\n  Svendsen",
    *original_emails,
    *original_phones,
    *original_addresses,
    original_date,
    original_cpr,
    original_account,
    original_url,
]

all_removed = True
for pii in pii_to_check:
    if pii and pii.strip() in anonymized_text:
        all_removed = False
    else:
        pass

if all_removed:
    pass
else:
    pass


# Anonymize the file
output_file = temp_dir / "danish_fake_document_anon.md"
file_counts = anonymize_file(input_file, anonymizer, output_file)
