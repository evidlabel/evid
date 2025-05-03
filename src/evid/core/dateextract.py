import re
import arrow
from pathlib import Path
from typing import List, Union
import fitz
from io import BytesIO


def extract_dates_from_pdf(
    pdf_source: Union[Path, BytesIO],
) -> List[Union[str, arrow.Arrow]]:
    if isinstance(pdf_source, Path):
        pdf = fitz.open(pdf_source)
    elif isinstance(pdf_source, BytesIO):
        pdf = fitz.open(stream=pdf_source, filetype="pdf")
    else:
        raise ValueError("pdf_source must be a Path or BytesIO object")

    text = "".join(page.get_text() for page in pdf)
    pdf.close()

    date_pattern = (
        r"\b(?:\d{1,2}[-/th|nd|rd|st\s\.]\s?(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s?\d{1,2}[,\s]*\d{2,4})|"
        r"\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b|"
        r"\b(?:\d{1,2}\.\s?(?:jan(?:uar)?|feb(?:ruar)?|mar(?:ts)?|apr(?:il)?|maj|jun(?:i)?|jul(?:i)?|aug(?:ust)?|sep(?:tember)?|okt(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s?\d{4})\b"
    )

    date_strings = re.findall(date_pattern, text, re.IGNORECASE)
    dates = []

    date_formats = [
        "DD/MM/YYYY",
        "DD-MM-YYYY",
        "DD.MM.YYYY",
        "D.MM.YYYY",
        "DD/MM/YY",
        "DD-MM-YY",
        "DD.MM.YY",
        "D. MMMM YYYY",
        "D. MMM YYYY",
        "D MMMM YYYY",
        "D MMM YYYY",
    ]

    for date_str in date_strings:
        for fmt in date_formats:
            try:
                date_obj = arrow.get(date_str.strip(), fmt, locale="da")
                dates.append(date_obj)
                break
            except arrow.parser.ParserError or ValueError:
                try:
                    date_obj = arrow.get(date_str.strip(), fmt, locale="en")
                    dates.append(date_obj)
                    break
                except arrow.parser.ParserError or ValueError:
                    continue

        else:
            dates.append(date_str)

    return dates
