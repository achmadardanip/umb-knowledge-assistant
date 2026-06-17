"""
Phase-12 STEP 5 — accreditation enrichment (faculty + program).

Accreditation grades/SK-numbers live mainly on the official accreditation AUTHORITIES
(BAN-PT, LAM-INFOKOM, LAMEMBA, LAM Teknik) and UMB accreditation pages/PDFs — explicitly
allowed for THIS field. Searches those domains, extracts HTML+PDF, LLM-parses
{accreditation, number}, and persists ONLY verbatim-verified values with evidence +
source_url (anti-hallucination: both grade and number must appear in the source text).

Run:  LOCAL_POSTGRES_MODE=true LOCAL_POSTGRES_URL=postgresql://umb:umb@localhost:5433/umb \
      PYTHONPATH=. python -m app.ingestion.accreditation_enrich [--write] [--programs]
→ reports/accreditation_enrichment_report.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import requests

from app.core.config import get_settings
from app.ingestion.official_ingest import extract_pdf

# Accreditation authorities + UMB (directive-allowed for the accreditation field only).
_ACCRED_DOMAINS = [
    "mercubuana.ac.id", "banpt.or.id", "ban-pt.kemdikbud.go.id",
    "laminfokom.org", "lamemba.or.id", "lamteknik.org",
]


def _accred_search(query: str, *, limit: int = 5) -> list[str]:
    s = get_settings()
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": s.tavily_api_key, "query": query, "search_depth": "advanced",
                  "max_results": limit, "include_domains": _ACCRED_DOMAINS},
            timeout=s.web_search_timeout_seconds,
        )
        resp.raise_for_status()
        return [it.get("url") for it in (resp.json().get("results") or []) if it.get("url")]
    except Exception:
        return []


def _fetch_text(url: str) -> str:
    if url.lower().split("?")[0].endswith(".pdf"):
        try:
            return extract_pdf(url)[0]
        except Exception:
            return ""
    try:
        from app.web_search.tavily_client import TavilyClient
        res = TavilyClient().extract([url])
        return res[0].raw_content if res else ""
    except Exception:
        return ""


def _llm_accred(text: str, entity: str, provider) -> dict:
    snippet = text[:6000]
    prompt = (
        "Ekstrak akreditasi dari teks resmi. JANGAN menebak; null jika tidak ada di TEKS.\n"
        f"Entitas: {entity}\n\nTEKS:\n{snippet}\n\n"
        'JSON saja: {"accreditation": <peringkat spt "Unggul"/"Baik Sekali"/"A"/"B"/null>, '
        '"number": <nomor SK akreditasi atau null>}'
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
    grade = data.get("accreditation")
    if isinstance(grade, str) and grade.strip() and grade.strip().lower() not in ("null", "none", "-") and grade.strip().lower() in low:
        out["accreditation"] = grade.strip()
    num = data.get("number")
    if isinstance(num, str) and num.strip() and num.strip().lower() not in ("null", "none", "-"):
        digits = re.sub(r"\D", "", num)
        if digits and digits[:6] in re.sub(r"\D", "", text):
            out["number"] = num.strip()
    return out


def _enrich(entities: list[tuple], label: str, provider, write_fn) -> list[dict]:
    records = []
    for ent in entities:
        name = ent[1]
        found, used_url, evidence = {}, None, None
        for q in (f"akreditasi {name} Universitas Mercu Buana", f"sertifikat akreditasi {name}", f"SK BAN-PT {name}"):
            for url in _accred_search(q)[:3]:
                txt = _fetch_text(url)
                if not txt:
                    continue
                fields = _llm_accred(txt, name, provider)
                if fields.get("accreditation"):
                    found, used_url = {**fields, **found}, url
                    idx = txt.lower().find(fields["accreditation"].lower())
                    evidence = txt[max(0, idx - 60): idx + 80].strip() if idx >= 0 else None
                    break
            if found.get("accreditation"):
                break
        rec = {"entity": name, "type": label, "accreditation": found.get("accreditation"),
               "number": found.get("number"), "source_url": used_url, "evidence": evidence,
               "verified": bool(found.get("accreditation"))}
        records.append(rec)
        if found.get("accreditation"):
            write_fn(ent[0], found.get("accreditation"), found.get("number"), used_url)
    return records


def run(*, write: bool, programs: bool) -> dict:
    from app.db.database import get_session_local
    from app.db.models import UMBFaculty, UMBStudyProgram
    from app.llm.provider_factory import get_provider

    provider = get_provider("local_ollama")
    SessionLocal = get_session_local()
    records = []

    if not programs:
        with SessionLocal() as db:
            facs = [(f.id, f.name) for f in db.query(UMBFaculty).all()]

        def wf(fid, grade, num, url):
            if not write:
                return
            with SessionLocal() as db:
                f = db.query(UMBFaculty).get(fid)
                if f and not f.accreditation_grade:
                    f.accreditation_grade = grade
                    if num:
                        f.accreditation_body = (f.accreditation_body or "") + f" SK:{num}"
                    db.commit()
        records = _enrich(facs, "faculty", provider, wf)
    else:
        with SessionLocal() as db:
            progs = [(p.id, f"{p.program_name} {p.degree_level}", p.faculty_name) for p in db.query(UMBStudyProgram).all()]

        def wf(pid, grade, num, url):
            if not write:
                return
            with SessionLocal() as db:
                p = db.query(UMBStudyProgram).get(pid)
                if p and not p.accreditation_grade:
                    p.accreditation_grade = grade
                    if num:
                        p.accreditation_body = (p.accreditation_body or "") + f" SK:{num}"
                    db.commit()
        records = _enrich([(p[0], p[1]) for p in progs], "program", provider, wf)

    verified = sum(1 for r in records if r["verified"])
    return {"summary": {"label": "program" if programs else "faculty", "total": len(records),
                        "with_accreditation": verified, "written": bool(write)}, "records": records}


def main() -> None:
    ap = argparse.ArgumentParser(description="Accreditation enrichment (faculty/program)")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--programs", action="store_true")
    args = ap.parse_args()
    result = run(write=args.write, programs=args.programs)
    rep = Path(__file__).resolve().parents[3] / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    name = "accreditation_programs" if args.programs else "accreditation_faculties"
    (rep / f"{name}_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    s = result["summary"]
    print(f"{s['label']}: {s['with_accreditation']}/{s['total']} accreditation (verbatim-verified)")
    for r in result["records"]:
        print(f"  {r['entity']:34s} acc={r['accreditation']!r} num={r['number']!r}")


if __name__ == "__main__":
    main()
