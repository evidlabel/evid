#set text(lang: "en")
#set text(font: "New Computer Modern", size: 12pt)

= Analysis of Ligature Replacement Issue

The `clean_text_for_typst` function is designed to expand Unicode ligatures (such as \ufb01 for "fi") into their component characters (e.g., "fi") before generating the Typst file.

== Issue Description
- When `page.get_text()` from PyMuPDF extracts text from the PDF, ligatures may be represented as separate characters rather than the single Unicode ligature characters.
- For example, "fi" might be extracted as 'f' and 'i' separately, not as \ufb01.
- Therefore, the text does not contain the Unicode ligature characters, so the replacement logic (`if lig in text: text.replace(lig, repl)`) does not trigger.
- The logger output confirms that ligatures are not found in the text, as no "Found ligature" messages are logged.
- Consequently, ligatures are not replaced, and if they appear in the `label.typ` output, it is because they were not present in the extracted text to begin with or were added by the user in the editor.

== Code Analysis
- The LIGATURES dictionary contains the correct Unicode ligature mappings.
- The replacement loop checks for each ligature in the text and replaces if found.
- Logging is added to detect when ligatures are found and replaced.
- However, since PyMuPDF likely extracts ligatures as separate glyphs, the Unicode ligatures are not in the string.

== Possible Solutions
- Remove the ligature replacement, as it may not be necessary if PyMuPDF already handles them as separate characters.
- Alternatively, implement a reverse replacement: replace sequences like "fi" with the ligature \ufb01, but this may not be desired.
- Investigate PyMuPDF options for text extraction that preserve ligatures.
- If ligatures are added by the user in the editor, ensure the replacement happens on the user's input, but that is not the case here.

== Conclusion
The ligature replacement fails because the extracted text does not contain the Unicode ligature characters. The code is correct, but the assumption that ligatures are present as single Unicode characters is incorrect for PyMuPDF's extraction.