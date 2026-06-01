# Complete Public UMB Indexing

Complete indexing means every discoverable public URL under `mercubuana.ac.id` or `*.mercubuana.ac.id` is either:

- indexed into the RAG knowledge base with chunks, or
- marked terminal non-indexable with a reason such as `http_404`, `http_403`, `robots_disallowed`, `empty_content`, `unsupported_content_type`, `file_too_large`, `download_failed`, or `extraction_failed`.

It does not mean brute-forcing infinite wildcard paths, and it does not mean indexing error/private/search pages as fake knowledge.

## Tooling

The full run requires external discovery tools. Install them into the repo-local `.tools` directory:

```bash
./scripts/install_discovery_tools.sh
```

The app automatically searches `.tools/bin` and `.tools/go/bin`.

Required for full discovery:

- `sublist3r`
- `katana`
- `gau`
- `waybackurls`

Optional:

- `hakrawler`
- `ffuf` and `dirsearch`, disabled by default because this project is for public indexing, not aggressive path enumeration

## Commands

Audit current state without crawling:

```bash
cd backend
.venv/bin/python -m app.ingestion.complete_index audit --domain mercubuana.ac.id
```

Run the full public discoverable indexing workflow:

```bash
cd backend
.venv/bin/python -m app.ingestion.complete_index run \
  --domain mercubuana.ac.id \
  --confirm-authorized
```

If external discovery tools are not installed and you only want to drain the current database backlog:

```bash
cd backend
.venv/bin/python -m app.ingestion.complete_index run \
  --domain mercubuana.ac.id \
  --confirm-authorized \
  --offline-current-db-only
```

Verify completion:

```bash
cd backend
.venv/bin/python -m app.ingestion.complete_index verify --domain mercubuana.ac.id
```

`verify` exits nonzero unless both are true:

- there are zero allowed, nonterminal, non-indexed discovered URLs
- there are zero invalid indexed sources, including unsafe-scope sources and sources marked `indexed` without chunks

## Resume Behavior

The workflow is safe to rerun. Indexed URLs remain indexed, terminal URLs remain terminal, and retryable failures are retried until `--max-attempts` is reached. After that, the URL is marked terminal with a clear reason so completeness can be audited.

The report is written to:

```text
data/reports/index_completeness.json
```

The report includes host-level counts, source-type counts, pending URL counts, terminal reason counts, unsafe indexed source samples, and final verification status.

## Safety Rules

Only URLs passing the official scope validator are eligible:

- `mercubuana.ac.id/*`
- `*.mercubuana.ac.id/*`

The workflow rejects lookalike domains and sensitive/private/generated paths such as login, admin, auth, password, token, `.env`, `.git`, webmail, phpMyAdmin, and search pages. Runtime retrieval also validates source scope, so previously indexed unsafe URLs are excluded from answers.
