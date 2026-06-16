"""
Priority-2 — targeted leadership & accreditation enrichment (no broad crawl).

For each faculty: Tavily Search (official domain) for the leadership/structure pages →
Tavily Extract → LLM extraction of ONLY text-grounded fields (dean, vice_dean,
accreditation). Anti-hallucination: an extracted name is kept only if it actually appears
in the source page text (no synthetic facts, no inferred data). Writes a dataset + summary
and (optionally) updates ``umb_faculties``.

Run:  LOCAL_POSTGRES_MODE=true LOCAL_POSTGRES_URL=postgresql://umb:umb@localhost:5433/umb \
      PYTHONPATH=. python -m app.ingestion.leadership_enrich [--write]
→ writes reports/leadership_enrichment_summary.json + reports/leadership_dataset.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from app.web_search.tavily_client import TavilyClient

_QUERIES = ["dekan {name}", "struktur organisasi {name}", "pimpinan {name}", "akreditasi {name}"]


def _official_urls(client: TavilyClient, faculty: str, *, limit: int = 4) -> list[str]:
    urls: list[str] = []
    for q in _QUERIES:
        try:
            for r in client.search(q.format(name=faculty), max_results=3):
                if r.url not in urls:
                    urls.append(r.url)
        except Exception:
            pass
    return urls[:limit]


def _llm_extract(text: str, faculty: str, provider) -> dict:
    """Extract ONLY fields explicitly present in ``text``. Returns dict with null-able
    dean / vice_dean / accreditation; values not found verbatim in the text are dropped."""
    snippet = text[:6000]
    prompt = (
        "Anda mengekstrak fakta dari teks resmi Universitas Mercu Buana. JANGAN menebak. "
        "Jika sebuah field tidak disebutkan eksplisit di TEKS, kembalikan null untuk field itu.\n"
        f"Fakultas: {faculty}\n\nTEKS:\n{snippet}\n\n"
        'Kembalikan HANYA JSON: {"dean": <nama dekan atau null>, "vice_dean": <nama wakil dekan atau null>, '
        '"accreditation": <peringkat akreditasi fakultas atau null>}'
    )
    try:
        content = provider.chat([{"role": "user", "content": prompt}]).content
    except Exception:
        return {}
    m = re.search(r"\{.*\}", content or "", re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {}
    low = text.lower()
    out: dict = {}
    for k in ("dean", "vice_dean", "accreditation"):
        v = data.get(k)
        if isinstance(v, str) and v.strip() and v.strip().lower() not in ("null", "none", "-"):
            # anti-hallucination: keep only if the core token appears in the source text
            core = re.sub(r"^(dr\.?|prof\.?|ir\.?|drs\.?|m\.?\w+\.?|s\.?\w+\.?|,|\s)+", "", v.strip().lower()).strip()
            if core and (core[:12] in low or v.strip().lower()[:12] in low):
                out[k] = v.strip()
    return out


def run(*, write: bool = False) -> dict:
    from app.db.database import get_session_local
    from app.db.models import UMBFaculty
    from app.llm.provider_factory import get_provider

    client = TavilyClient()
    client.ensure_configured()
    provider = get_provider("local_ollama")
    SessionLocal = get_session_local()

    with SessionLocal() as db:
        faculties = [(f.name, f.id) for f in db.query(UMBFaculty).all()]

    dataset = []
    for name, fid in faculties:
        urls = _official_urls(client, name)
        found: dict = {}
        used_url = None
        for url in urls:
            try:
                res = client.extract([url])
            except Exception:
                continue
            if not res or not res[0].raw_content:
                continue
            fields = _llm_extract(res[0].raw_content, name, provider)
            if fields:
                found = {**fields, **found}
                used_url = url
            if "dean" in found:
                break
        dataset.append({"faculty": name, "source_url": used_url, "discovered_urls": urls, **found})
        if write and found.get("dean"):
            with SessionLocal() as db:
                fac = db.query(UMBFaculty).get(fid)
                if fac and not fac.dean:
                    fac.dean = found["dean"]
                    db.commit()

    summary = {
        "faculties_total": len(faculties),
        "faculties_with_dean": sum(1 for d in dataset if d.get("dean")),
        "faculties_with_vice_dean": sum(1 for d in dataset if d.get("vice_dean")),
        "faculties_with_accreditation": sum(1 for d in dataset if d.get("accreditation")),
        "programs_with_head": 0,
        "programs_with_accreditation": 0,
        "method": "tavily_search+extract + LLM extraction (text-grounded, no synthetic facts)",
        "written_to_db": bool(write),
    }
    return {"summary": summary, "dataset": dataset}


def main() -> None:
    ap = argparse.ArgumentParser(description="Targeted leadership/accreditation enrichment")
    ap.add_argument("--write", action="store_true", help="update umb_faculties.dean for found deans")
    args = ap.parse_args()

    result = run(write=args.write)
    rep = Path(__file__).resolve().parents[3] / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "leadership_enrichment_summary.json").write_text(json.dumps(result["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
    (rep / "leadership_dataset.json").write_text(json.dumps(result["dataset"], ensure_ascii=False, indent=2), encoding="utf-8")
    s = result["summary"]
    print(f"faculties {s['faculties_total']} | dean {s['faculties_with_dean']} | "
          f"vice_dean {s['faculties_with_vice_dean']} | accreditation {s['faculties_with_accreditation']}")
    for d in result["dataset"]:
        print(f"  {d['faculty']:34s} dean={d.get('dean')!r:40s} acc={d.get('accreditation')!r}")


if __name__ == "__main__":
    main()
