from __future__ import annotations

from bs4 import BeautifulSoup


def extract_html_tables(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    tables: list[dict] = []
    for index, table in enumerate(soup.find_all("table")):
        rows = []
        for tr in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if not rows:
            continue
        columns = rows[0]
        body = rows[1:]
        summary_lines = [
            f"Tabel {index + 1}",
            "Kolom: " + ", ".join(columns),
        ]
        for row_number, row in enumerate(body[:25], start=1):
            summary_lines.append(f"Baris {row_number}: " + " | ".join(row))
        tables.append(
            {
                "table_index": index,
                "columns": columns,
                "row_count": len(body),
                "content": "\n".join(summary_lines),
                "row_range": f"1-{min(len(body), 25)}" if body else None,
            }
        )
    return tables

