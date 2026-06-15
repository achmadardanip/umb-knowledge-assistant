-- v3 P5: ONE-TIME chunk metadata prune (egress + storage reduction).
--
-- chunks.metadata averaged ~13 KB/row (max 82 KB), dominated by EPrints/repository
-- junk the retriever never reads (`links` ~30 KB, full `DC.description` /
-- `eprints.abstract`, `images`, dozens of `DC.*`/`eprints.*`). This rewrites every
-- bloated row to the small retrieval allowlist, ENTIRELY SERVER-SIDE (no egress for
-- the rewrite). New chunks are kept lean at ingest by app.ingestion.metadata_pruning.
--
-- ⚠️ DESTRUCTIVE & IRREVERSIBLE: the stripped keys are not stored elsewhere. Review
-- the allowlist, then run intentionally. Prefer:
--   PYTHONPATH=. .venv/Scripts/python.exe -m app.ingestion.metadata_pruning
-- (After running, VACUUM (or wait for autovacuum) reclaims storage; egress drops
--  immediately because retrieval reads the smaller metadata.)

UPDATE chunks
SET metadata = COALESCE((
    SELECT jsonb_object_agg(kv.key, kv.value)
    FROM jsonb_each(metadata) AS kv
    WHERE kv.key = ANY(ARRAY[
        'url','hostname','title','path',
        'source_type','content_type','media_type','page_type',
        'discovery_source','ingested_via','extraction_method','extraction_confidence',
        'page_number','slide_number','sheet_name','row_range',
        'timestamp_start','timestamp_end','language','chunk_index','priority'
    ])
), '{}'::jsonb)
WHERE metadata IS NOT NULL
  AND length(metadata::text) > 600;
