# Pipeline

The end-to-end pipeline is exposed through:

```bash
postdoc-scout run-pipeline --institution "Harvard University" --mode broad --country us --output-dir outputs/harvard
```

## Stages

1. `institution_mapping`: creates `ecosystem.json` and `ecosystem.md`.
2. `query_building`: creates `discovery_queries.json` and `discovery_queries.md`.
3. `evidence_collection`: creates `evidence_collection.json` and `evidence_collection.md`.
4. `candidate_extraction`: creates JSON, Markdown, and CSV candidate extraction reports.
5. `candidate_ranking`: creates JSON, Markdown, and CSV ranked supervisor reports.
6. `candidate_enrichment`: creates JSON, Markdown, and CSV enriched supervisor reports.

The run also writes `pipeline_run.json` and `pipeline_summary.md`.

## Dry Run

```bash
postdoc-scout run-pipeline --institution "Harvard University" --mode broad --country us --dry-run --output-dir outputs/harvard_dry_run
```

Dry run stops after ecosystem mapping and query building. It does not call external APIs.

## Resume and Skip Controls

- `--resume` reuses existing stage outputs when present.
- `--no-resume` overwrites previous outputs.
- `--skip-evidence-collection` reuses an existing `evidence_collection.json`.
- `--skip-enrichment` still produces ranked supervisor reports.
- `--limit-queries`, `--limit-per-source`, and `--top-n` constrain the run.

## Failure Behavior

Stage failures are represented in `pipeline_run.json` with structured status, warnings, and errors. Downstream stages are skipped when required upstream artifacts are unavailable.

