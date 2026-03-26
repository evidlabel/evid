Test Document for De-ID
This document tests the De-ID CLI tool with names and numbers
for anonymization based on config.yaml.
Names
• Exact: John Doe is a project manager.
• Fuzzy: Jon Doe was in the report.
• Exact: Jane Smith leads development.
• Fuzzy: Jane Smyth attended the meeting.
• Edge Case: john DOE (mixed case) wrote a memo.
Numbers
• Exact: Account number: 1234567890.
• Pattern: Security code: 12 34 56 78.
• Multiline: Phone: 1234567
890 across two lines.
Mixed Content
Contact John Doe at 1234567890 or Jane Smith via 12 34 56 78. Jon Doe and
Jane Smyth share details. A record lists john DOE with code 12 34 56 78.
This ensures exact, fuzzy, and pattern-based anonymization works.


John Doe lives at 123 One Street, Springfield, US and can be reached at john.doe@example.com.
