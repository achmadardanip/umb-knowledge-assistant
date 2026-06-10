# UMB Knowledge Assistant

UMB Knowledge Assistant adalah MVP chatbot RAG multimodal untuk menjadi _single source of truth_ informasi publik Universitas Mercu Buana berdasarkan domain resmi `mercubuana.ac.id` dan `*.mercubuana.ac.id`.

Sistem ini bukan chatbot FAQ generik. Jawaban hanya boleh disusun dari sumber publik resmi yang berhasil ditemukan, di-crawl, dibersihkan, diindeks, dan dikembalikan sebagai konteks RAG dengan sitasi.

## Masalah

Ekosistem website resmi UMB memiliki banyak halaman, subdomain, dokumen, dan media publik. Tanpa satu chatbot terpadu, pengguna harus mencari manual di banyak tempat. MVP ini menyediakan alur otomatis untuk menemukan sumber publik resmi, mengindeksnya, lalu menjawab pertanyaan dalam bahasa Indonesia dengan sumber yang dapat diverifikasi.

## Mengapa RAG

RAG digunakan karena informasi kampus berubah dari waktu ke waktu. Model LLM tidak dijadikan sumber kebenaran. LLM hanya menyusun jawaban dari konteks resmi yang diambil oleh retriever. Jika konteks resmi tidak ditemukan, sistem wajib menjawab:

> Saya belum menemukan informasi resmi terkait pertanyaan tersebut pada sumber publik Universitas Mercu Buana yang tersedia.

## Arsitektur

- Backend: FastAPI, SQLAlchemy, Supabase PostgreSQL, pgvector.
- Frontend: Next.js, React, Tailwind CSS.
- Discovery: Sublist3r, Katana, Hakrawler, gau, waybackurls, ffuf/dirsearch opsional.
- Crawling: domain-scoped crawler, robots.txt check, rate limit konservatif.
- Ekstraksi: HTML, PDF, DOCX, PPTX, spreadsheet/CSV, OCR opsional, ASR opsional, metadata video opsional.
- Ingestion: source-aware chunking, embedding provider abstraction.
- Retrieval: hybrid keyword/vector-ready retrieval dengan metadata sitasi.
- LLM: Ollama lokal default, LM Studio opsional, serta provider cloud dan Puter sebagai fallback.
- Chat: session history, source cards, visible operational steps, memory aman.

## Supabase PostgreSQL

Gunakan Supabase PostgreSQL sebagai database utama. Format variabel:

```env
DATABASE_URL=postgresql+psycopg://postgres:<SUPABASE_DB_PASSWORD>@db.<SUPABASE_PROJECT_REF>.supabase.co:5432/postgres
```

Jangan hardcode connection string di source code. Simpan hanya di `.env`.

Untuk GitHub Actions, gunakan Supabase pooler jika direct database host gagal karena IPv6 di GitHub-hosted runner. Tambahkan repository secret:

```env
SUPABASE_POOLER_DATABASE_URL=postgresql+psycopg://postgres.<SUPABASE_PROJECT_REF>:<SUPABASE_DB_PASSWORD>@aws-0-<SUPABASE_REGION>.pooler.supabase.com:6543/postgres
```

Secret ini akan dipakai oleh workflow freshness sebagai `DATABASE_URL`. Secret `DATABASE_URL` tetap bisa dipakai untuk runtime lokal/server yang dapat menjangkau host direct Supabase.

Untuk pipeline indexing production/demo, gunakan Supabase PostgreSQL saja dan matikan fallback SQLite agar tidak ada data KB tersimpan lokal tanpa sengaja:

```env
LOCAL_SQLITE_FALLBACK_ENABLED=false
LOCAL_SQLITE_PATH=local-dev.db
```

Jika perlu eksperimen development terisolasi, fallback SQLite tetap tersedia, tetapi jangan dipakai untuk ingestion knowledge base resmi.

## pgvector

Jalankan SQL berikut melalui Supabase SQL Editor atau migration runner:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

File lengkap tersedia di `backend/app/db/migrations/setup_pgvector.sql`.

Untuk database yang sudah ada, local E5 memakai tabel sidecar non-destruktif
`chunk_embeddings`; vector Gemini/OpenAI lama di `chunks.embedding` tidak diubah:

```bash
psql "$(printf '%s' "$DATABASE_URL" | sed 's#^postgresql+psycopg://#postgresql://#')" \
  -f backend/app/db/migrations/add_chunk_embeddings.sql
```

Migration tersebut sengaja dijalankan manual. Aplikasi tidak mengubah schema
Supabase saat startup.

## Local E5 Embeddings

Local embedding pertama yang didukung adalah
`intfloat/multilingual-e5-small` (384 dimensi):

```bash
cd backend
.venv/bin/pip install -r requirements-local.txt
```

```env
EMBEDDING_PROVIDER=local_e5
EMBEDDING_MODEL=intfloat/multilingual-e5-small
EMBEDDING_PROFILE=local-e5-small-v1
LOCAL_EMBEDDING_DIMENSION=384
LOCAL_EMBEDDING_DEVICE=auto
```

Audit kandidat tanpa model inference atau database write:

```bash
PYTHONPATH=. .venv/bin/python -m app.ingestion.embed_backfill \
  --dry-run --only-keyword-only --limit 100
```

Setelah migration dan evaluasi siap, jalankan backfill secara eksplisit:

```bash
PYTHONPATH=. .venv/bin/python -m app.ingestion.embed_backfill \
  --only-keyword-only --batch-size 32
```

Cloud embeddings dan provider generation tetap tersedia. Jangan aktifkan
`DENSE_RETRIEVAL_ENABLED=true` sebelum profile lokal selesai di-backfill.

## Local Multilingual Reranker

Reranker lintas bahasa memakai `BAAI/bge-reranker-v2-m3` melalui
`sentence-transformers`. Fitur ini opt-in dan mempertahankan ranking
heuristic/TAHF bila model gagal dimuat atau inference gagal:

```env
RERANKER_ENABLED=false
RERANKER_PROVIDER=local_bge
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_DEVICE=auto
RERANKER_CANDIDATE_K=20
RERANKER_BATCH_SIZE=4
RERANKER_MAX_LENGTH=512
RERANKER_MODEL_WEIGHT=0.8
RERANKER_PREWARM_ENABLED=true
```

Jalankan gate kualitas dan latensi sebelum mengaktifkannya:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m app.evaluation.benchmark_reranker \
  --out /tmp/umb-reranker-gate.json
```

Exit code `0` berarti seluruh gate lolos. Exit code `1` berarti reranker harus
tetap nonaktif. Profil fallback yang diizinkan dapat diuji tanpa mengubah
`.env`:

```bash
RERANKER_CANDIDATE_K=12 RERANKER_MAX_LENGTH=384 \
PYTHONPATH=. .venv/bin/python -m app.evaluation.benchmark_reranker \
  --out /tmp/umb-reranker-gate-12x384.json
```

## Setup Provider AI

Default answer provider adalah Ollama lokal:

```env
ANSWER_PROVIDER=local_ollama
LOCAL_LLM_BASE_URL=http://localhost:11434
LOCAL_LLM_MODEL=qwen2.5:7b-instruct
LOCAL_LLM_TEMPERATURE=0.2
LOCAL_LLM_MAX_TOKENS=800
ANSWER_FALLBACK_PROVIDER=puter
ANSWER_ENABLE_FALLBACK=true
```

Provider yang didukung:

- Ollama lokal: `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL`
- LM Studio lokal: `LMSTUDIO_BASE_URL`, `LMSTUDIO_MODEL`
- OpenRouter: `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`
- OpenAI: `OPENAI_API_KEY`, `OPENAI_MODEL`
- Gemini: `GEMINI_API_KEY`, `GEMINI_MODEL`
- Claude/Anthropic: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- Hermes Agent API Server: `HERMES_ENABLED`, `HERMES_BASE_URL`, `HERMES_API_KEY`, `HERMES_MODEL`

Puter tetap berjalan di browser melalui `/chat/prepare` dan `/chat/finalize`;
retrieved context, validasi sitasi, dan CGCV tetap dikendalikan backend.
Frontend mengirim `provider_override` pada setiap request chat. API key tidak
pernah dikirim ke frontend.

## Discovery dan Crawling

Sistem hanya dimulai dari satu root domain:

```env
DISCOVERY_DOMAIN=mercubuana.ac.id
```

Tidak ada seed subdomain manual yang di-hardcode. Sublist3r digunakan untuk menemukan subdomain publik. Jika tidak ada hasil, root domain `mercubuana.ac.id` digunakan sebagai fallback minimal, bukan daftar seed manual.

Alur:

1. `Sublist3r` menemukan subdomain publik.
2. Host divalidasi hanya jika `mercubuana.ac.id` atau `*.mercubuana.ac.id`.
3. `Katana` dan `Hakrawler` melakukan crawling URL publik dari host valid.
4. `gau` dan `waybackurls` mengumpulkan kandidat URL dari arsip publik.
5. URL arsip tidak diindeks langsung. Sistem mengubahnya menjadi kandidat URL live resmi dan hanya mengindeks jika halaman live valid.
6. `ffuf` dan `dirsearch` opsional, nonaktif default, hanya memakai `data/wordlists/safe_public_paths.txt`.
7. URL login, admin, private, token, password, `.env`, `.git`, phpMyAdmin, webmail, dan path sensitif lain ditolak.

Semua discovery eksternal wajib memakai flag:

```bash
python -m app.discovery.discovery_pipeline discover-subdomains --domain mercubuana.ac.id --confirm-authorized
python -m app.discovery.discovery_pipeline discover-urls --domain mercubuana.ac.id --max-depth 3 --confirm-authorized
python -m app.discovery.discovery_pipeline merge-filter
```

Tujuan pipeline ini adalah indexing informasi publik, bukan penetration testing, vulnerability scanning, exploitation, brute force, atau bypass autentikasi.

## Multimodal Ingestion

Jenis sumber publik yang didukung:

- HTML
- PDF
- DOCX
- PPTX
- XLSX/CSV
- Gambar dengan OCR
- Transcript/caption
- Audio/video metadata dan transcript

OCR, ASR, dan video download nonaktif default:

```env
ENABLE_OCR=false
ENABLE_ASR=false
ENABLE_VIDEO_DOWNLOAD=false
```

Metadata yang dipertahankan:

- PDF: nomor halaman
- PPTX: nomor slide
- Spreadsheet: sheet name dan row range
- Audio/video transcript: timestamp
- OCR/ASR: extraction method dan confidence

Command:

```bash
python -m app.multimodal.multimodal_pipeline classify-discovered
python -m app.multimodal.multimodal_pipeline download-assets --max-files 200
python -m app.multimodal.multimodal_pipeline extract-assets
python -m app.multimodal.multimodal_pipeline index-assets
python -m app.multimodal.multimodal_pipeline run-all --max-files 200
```

Sumber multimodal tetap dibatasi ke `mercubuana.ac.id` dan `*.mercubuana.ac.id`. File privat, authenticated, atau protected tidak diproses.

## Menjalankan Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Health check:

```bash
curl http://localhost:8000/health
```

## Menjalankan Frontend

```bash
cd frontend
npm install
npm run dev
```

Buka `http://localhost:3000`.

## Docker Compose

Salin `.env.example` menjadi `.env`, isi Supabase dan provider key, lalu:

```bash
docker compose up --build
```

Compose hanya menjalankan backend dan frontend. Database default adalah Supabase PostgreSQL eksternal. Service PostgreSQL lokal tersedia sebagai komentar untuk development lokal.

## Ingestion HTML

Setelah discovery:

```bash
python -m app.ingestion.pipeline crawl-discovered --max-pages 500 --rate-limit 2
```

Atau crawl domain secara langsung dengan konfirmasi:

```bash
python -m app.ingestion.pipeline crawl --domain mercubuana.ac.id --max-pages 500 --max-depth 3 --confirm-authorized
```

## Firecrawl to Supabase KB

Firecrawl self-hosted dipakai untuk Search, Map, Crawl, Scrape, dan parser
HTML/PDF ke Supabase. Base URL tanpa suffix otomatis diarahkan ke API v2:

```env
FIRECRAWL_API_KEY=
FIRECRAWL_BASE_URL=http://localhost:3002
FIRECRAWL_SELF_HOSTED=true
FIRECRAWL_DEFAULT_LIMIT=500
FIRECRAWL_ZERO_DATA_RETENTION=false
```

Import seed JSON resmi:

```bash
cd backend
.venv/bin/python -m app.ingestion.umb_crawl import-seeds \
  --seed-json /path/to/mercubuana.ac.id.json \
  --source official_umb --confirm-authorized
```

Full refresh:

```bash
.venv/bin/python -m app.ingestion.umb_crawl full-refresh \
  --confirm-authorized --seed-json /path/to/mercubuana.ac.id.json \
  --domains mercubuana.ac.id --include-subdomains --include-sitemap \
  --use-firecrawl-search --use-firecrawl-map --use-firecrawl-crawl \
  --use-firecrawl-scrape --use-firecrawl-parse --use-tavily-gap-fill \
  --include-multimodal --parse-pdf \
  --index-images-metadata --index-video-metadata \
  --store-supabase --update-graph --max-depth 4 --limit 10000
```

Pipeline menolak auth/admin dan domain eksternal, melewati URL yang sudah
mempunyai chunk, membersihkan CTA/navbar berulang, dan menghasilkan laporan di
`reports/`. `intfloat/multilingual-e5-small` tetap embedding retrieval produksi.
Jina v4 dan Qwen2.5-VL tersedia sebagai configuration hooks dan nonaktif default.

## Complete Public Indexing

Untuk menuntaskan knowledge base publik UMB, gunakan workflow lengkap:

```bash
cd backend
.venv/bin/python -m app.ingestion.complete_index audit --domain mercubuana.ac.id
.venv/bin/python -m app.ingestion.complete_index run --domain mercubuana.ac.id --confirm-authorized
.venv/bin/python -m app.ingestion.complete_index verify --domain mercubuana.ac.id
```

Definisi selesai: setiap URL publik yang dapat ditemukan di `mercubuana.ac.id/*` dan `*.mercubuana.ac.id/*` sudah masuk index RAG, atau ditandai terminal non-indexable dengan alasan jelas seperti `http_404`, `http_403`, `robots_disallowed`, `empty_content`, `unsupported_content_type`, `file_too_large`, `download_failed`, atau `extraction_failed`.

Full run membutuhkan tool discovery eksternal (`sublist3r`, `katana`, `gau`, `waybackurls`). Install ke repo-local `.tools`:

```bash
./scripts/install_discovery_tools.sh
```

Jika tool belum tersedia dan hanya ingin menghabiskan backlog URL yang sudah ada di database:

```bash
cd backend
.venv/bin/python -m app.ingestion.complete_index run --domain mercubuana.ac.id --confirm-authorized --offline-current-db-only
```

`verify` gagal jika masih ada URL allowed nonterminal yang belum diproses, source unsafe, atau source berstatus `indexed` tanpa chunk. Report ditulis ke `data/reports/index_completeness.json`. Runbook lengkap ada di `docs/complete_indexing.md`.

## Chat Session dan History

Frontend menyimpan `anonymous_session_id`, `last_active_session_id`, `selected_provider`, dan preferensi memori di localStorage. Backend menyimpan:

- `chat_sessions`
- `chat_messages`
- sources, confidence, provider/model, visible steps, timestamps

Fitur tersedia:

- New Chat
- Riwayat chat
- Load pesan lama
- Rename session
- Soft delete session

## Chat Memory

Memory bersifat opsional dan aman. Memory hanya dipakai untuk kontinuitas, bukan sebagai sumber resmi. Sistem meredaksi password, OTP, API key, bearer token, dan database URL sebelum menyimpan pesan/memory.

Official RAG context selalu mengalahkan memory untuk klaim institusional.

## Evaluasi

File pertanyaan:

```text
backend/app/evaluation/eval_questions.json
```

Jalankan:

```bash
cd backend
python -m app.evaluation.evaluate_rag --top-k 5 --out data/evaluation_report.json
```

Bandingkan mode retrieval sebelum mengaktifkan dense secara default:

```bash
PYTHONPATH=. .venv/bin/python -m app.evaluation.evaluate_rag \
  --strategies keyword,dense,hybrid --top-k 5 \
  --out data/evaluation_comparison.json
```

Report mencakup retrieval hit rate, labelled source-target hit rate, abstention,
host yang ditemukan, dan fixture grounding/citation offline.

## Testing

```bash
cd backend
pytest
```

Test mencakup scope validation, private path rejection, URL normalization, provider factory, redaction, chat sessions, memory, citation validation, discovery safety, classifier, extraction scaffold, dan retrieval metadata.

## Security Notes

- Jangan commit `.env`.
- Jangan expose API key ke frontend.
- Discovery wajib `--confirm-authorized`.
- ffuf dan dirsearch disabled default.
- OCR, ASR, video download disabled default.
- Tidak mengambil data mahasiswa privat, SIA account, dashboard, admin panel, login behind auth, atau personal data.
- Archive URL hanya kandidat, bukan sumber resmi current.
- Low-confidence OCR/ASR tidak boleh menghasilkan high-confidence answer.

## Limitasi MVP

- Dense retrieval bersifat opt-in. PostgreSQL memakai HNSW pgvector untuk profile E5 384 dimensi; SQLite test/dev memakai cosine scan.
- Legacy cloud vectors tanpa provenance tetap disimpan di `chunks.embedding` dan tidak dicampur dengan profile lokal.
- Multimodal DB indexing penuh disiapkan melalui model dan metadata, sementara CLI MVP menghasilkan extraction report dan chunk-ready output.
- ASR/OCR/yt-dlp metadata membutuhkan dependency sistem tambahan jika diaktifkan.
- Belum ada authentication user account atau admin dashboard.

## Roadmap

- GraphRAG dengan knowledge graph.
- Admin dashboard.
- Scheduled recrawling.
- RAGAS evaluation.
- Authenticated student assistant dengan integrasi SSO, hanya dengan izin resmi.
- WhatsApp/Telegram integration.
- Multilingual support.
- Role-based access control.
- User account memory.
- Incremental crawling dan recrawling scheduler.
- Better multimodal vision understanding jika aman dan berizin.
