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
- LLM: provider abstraction untuk OpenRouter, OpenAI, Gemini, dan Claude/Anthropic.
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

Untuk development lokal, aplikasi otomatis fallback ke SQLite `backend/local-dev.db` jika direct Supabase tidak bisa dijangkau, misalnya karena host direct hanya resolve ke IPv6. Fallback ini dikontrol oleh:

```env
LOCAL_SQLITE_FALLBACK_ENABLED=true
LOCAL_SQLITE_PATH=local-dev.db
```

## pgvector

Jalankan SQL berikut melalui Supabase SQL Editor atau migration runner:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

File lengkap tersedia di `backend/app/db/migrations/setup_pgvector.sql`.

## Setup Provider AI

Default provider adalah OpenRouter:

```env
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=
OPENROUTER_MODEL=openai/gpt-oss-20b:free
```

Provider yang didukung:

- OpenRouter: `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`
- OpenAI: `OPENAI_API_KEY`, `OPENAI_MODEL`
- Gemini: `GEMINI_API_KEY`, `GEMINI_MODEL`
- Claude/Anthropic: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- Hermes Agent API Server: `HERMES_ENABLED`, `HERMES_BASE_URL`, `HERMES_API_KEY`, `HERMES_MODEL`

Frontend mengirim `provider_override` pada setiap request chat. API key tidak pernah dikirim ke frontend.

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

Report mencakup sources found, citation count, not_found rate, provider used, memory_used=false, dan distribusi source type.

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

- Vector search siap secara schema, tetapi retriever MVP memakai keyword scoring portable agar test dan local setup tetap ringan. Supabase pgvector SQL sudah disediakan untuk perluasan.
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
