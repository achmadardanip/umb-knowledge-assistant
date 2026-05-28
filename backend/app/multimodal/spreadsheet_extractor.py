from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractedSheet:
    sheet_name: str
    content: str
    row_range: str | None
    columns: list[str]
    extraction_method: str
    extraction_confidence: float = 0.8


def _summarize_rows(sheet_name: str, rows: list[list[str]], method: str) -> ExtractedSheet:
    if not rows:
        return ExtractedSheet(sheet_name, "", None, [], method, 0.2)
    columns = [str(cell) for cell in rows[0]]
    body = rows[1:51]
    lines = [f"Sheet: {sheet_name}", "Kolom: " + ", ".join(columns)]
    for index, row in enumerate(body, start=1):
        lines.append(f"Baris {index}: " + " | ".join(str(cell) for cell in row))
    return ExtractedSheet(
        sheet_name=sheet_name,
        content="\n".join(lines),
        row_range=f"1-{len(body)}" if body else None,
        columns=columns,
        extraction_method=method,
    )


def extract_spreadsheet(path: str | Path, source_type: str) -> list[ExtractedSheet]:
    target = Path(path)
    if source_type == "csv":
        with target.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            rows = [row for row in csv.reader(handle)]
        return [_summarize_rows(target.stem or "CSV", rows, "csv")]

    try:
        import pandas as pd

        sheets = pd.read_excel(target, sheet_name=None, nrows=51)
        extracted: list[ExtractedSheet] = []
        for sheet_name, frame in sheets.items():
            rows = [list(frame.columns)] + frame.astype(str).values.tolist()
            extracted.append(_summarize_rows(str(sheet_name), rows, "pandas/openpyxl"))
        return extracted
    except Exception:
        return []

