# postdoc-scout-agent

An open-source MVP for identifying, ranking, and auditing potential postdoctoral supervisors in translational digital medicine and clinical AI.

The project is designed for scouting supervisors whose work is close to patient-facing biomedical applications, including:

- digital medicine and clinical AI
- AD/ADRD, oncology, and other translational disease areas
- EHR-based prediction and real-world data studies
- disease risk prediction, progression modeling, and patient stratification
- clinical decision support and cohort-based biomedical AI

It is not primarily aimed at pure biostatistics methodology, statistical theory, standalone ML algorithm development, or foundation model architecture searches.

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

Run the placeholder scout command:

```bash
postdoc-scout scout --institution "Harvard Medical School" --mode broad --limit 20
```

The current command returns a structured placeholder summary. Future versions will add source connectors, candidate extraction, evidence audit trails, and ranking outputs.

## Institution Ecosystem Mapper

Before discovering individual supervisors, the agent first maps the institution-level ecosystem. This turns a query such as `Harvard University` into an auditable list of relevant schools, affiliated hospitals, disease centers, biomedical informatics units, digital medicine groups, public health departments, and partner institutes.

This step matters because postdoctoral supervisors in translational digital medicine and clinical AI are often distributed across medical schools, hospitals, cancer centers, neuroscience centers, public health schools, and research institutes rather than a single department.

Run:

```bash
postdoc-scout map-institution --institution "Harvard University" --mode broad
```

By default this writes:

```text
outputs/harvard_university_ecosystem.json
outputs/harvard_university_ecosystem.md
```

Example output summary:

```text
Institution: Harvard University
Mode: broad
Units: 7
Top units:
- Dana-Farber Cancer Institute
- Massachusetts General Hospital
- Brigham and Women's Hospital
- Broad Institute of MIT and Harvard
- Harvard Medical School
```

Use `--mode narrow` for AD/ADRD, aging, neurodegeneration, neurology, and neuroscience-focused mapping. Use `--format json`, `--format md`, or `--format both` to control report outputs.

The mapper currently uses only `configs/institution_affiliates.yml`. The curated entries are seed data, not exhaustive institutional truth. They should be verified before outreach, ranking, or publication-quality reporting. The module does not scrape websites, call external APIs, or require API keys.

## U.S. Curated Seed Map

The mapper now includes a U.S.-focused curated seed layer for universities, academic medical centers, cancer centers, health systems, pediatric hospitals, and independent biomedical research institutes.

This seed layer is not a legal affiliation database. It is a pragmatic discovery aid for postdoctoral supervisor scouting, where relevant labs may sit in medical schools, hospitals, cancer centers, public health schools, biomedical informatics units, digital medicine groups, or independent institutes near a university ecosystem.

Every U.S. parent institution and unit is marked `curated_seed_needs_verification` until automated verification is implemented. Relationship labels are intentionally conservative:

- `owned_by` is used only for obvious parent-owned units in the seed map.
- `affiliated_with`, `partner_ecosystem`, and `nearby_ecosystem` are used when useful for scouting but should not be read as a legal affiliation claim.
- `needs_verification` is used where the unit is a plausible discovery target but requires confirmation before outreach or reporting.

List available U.S. seed parents:

```bash
postdoc-scout list-institutions --country us --tier all
postdoc-scout list-institutions --country us --tier A
```

Map a university ecosystem:

```bash
postdoc-scout map-institution --institution "Harvard University" --mode broad --country us
```

Map a cancer center as a parent institution:

```bash
postdoc-scout map-institution --institution "MD Anderson Cancer Center" --mode broad --country us
```

Academic medical centers, cancer centers, health systems, and independent research institutes are included alongside universities because translational digital medicine, clinical AI, EHR/RWD, AD/ADRD, oncology, clinical decision support, trial enrichment, and patient stratification work often lives outside traditional university departments.

## Seed Map Validation

Validate the curated U.S. seed map before extending it:

```bash
postdoc-scout validate-seed-map --country us --output-dir outputs
```

This writes:

```text
outputs/us_seed_map_validation.json
outputs/us_seed_map_coverage.md
```

The validator checks required parent and unit fields, controlled relationship labels, priority tiers, duplicate names, list-shaped aliases/domains/source URLs, and unsupported relevance domains. It also generates coverage counts by tier, parent type, unit type, and relevance domain.

Relationship warnings are expected in the current seed layer. They flag cases where a unit is labeled `owned_by` or `affiliated_with` while still marked `curated_seed_needs_verification`. These warnings do not fail validation; they are reminders that the seed map is curated and requires future automated verification before it should be treated as evidence of formal affiliation.

## Candidate Scoring Framework

The candidate scoring framework defines how potential postdoctoral supervisors are represented, scored, ranked, and audited before any live data connectors are added.

Digital medicine, clinical AI, disease-domain translation, EHR/RWD, oncology, AD/ADRD, clinical decision support, public health, trial enrichment, and patient stratification are weighted highly because the project is designed for translational supervisor scouting, not generic academic prestige ranking.

Pure biostatistical theory, standalone algorithm development, benchmark-only machine learning, and foundation model architecture work are downweighted unless there is explicit evidence connecting the methods to clinical translation, real-world data, disease applications, or deployable digital medicine. Method-heavy profiles receive only a modest penalty so a strong translational methods candidate can still rank well.

Each score dimension includes a numeric score, stars, weight, weighted contribution, explanation, warnings, and supporting evidence IDs. Candidate reports preserve publication, grant, lab-page, and manual-note evidence so scores can be traced back to auditable source items.

Run deterministic mock scoring:

```bash
postdoc-scout score-mock-candidates --input examples/mock_candidates.yml --output-dir outputs
```

This writes:

```text
outputs/mock_candidate_scores.json
outputs/mock_candidate_scores.md
```

## Supervisor Discovery Query Builder

The query builder bridges institution ecosystem mapping and future source connectors. It turns a mapped institution and its relevant units into auditable query templates before any PubMed, OpenAlex, Semantic Scholar, NIH RePORTER, or web/lab-page API calls are made.

Query generation happens first so the search strategy can be inspected, deduplicated, and tuned before live evidence collection. Each query preserves the institution unit, unit type, mode, relevance domains, priority, expected evidence type, and rationale.

Broad mode emphasizes digital medicine, clinical AI, EHR/RWD, oncology digital medicine, clinical decision support, risk prediction, patient stratification, trial enrichment, public health, and biomedical informatics. Narrow mode emphasizes AD/ADRD, Alzheimer's disease, dementia, aging, neurodegeneration, cognitive decline, neurology, memory centers, and biomarker terms.

Run:

```bash
postdoc-scout build-queries --institution "Harvard University" --mode broad --output-dir outputs
```

This writes:

```text
outputs/harvard_university_discovery_queries.json
outputs/harvard_university_discovery_queries.md
```

The generated bundle is deterministic and does not call external APIs, scrape websites, require API keys, or claim that any evidence has already been collected. Future connectors will consume these query bundles and attach source evidence to supervisor candidates.

## External Connector Layer v0

The external connector layer consumes generated discovery query bundles and collects publication evidence candidates from public scholarly sources. This stage still does not rank supervisors or verify individual candidate identity.

OpenAlex is used for open scholarly graph search. PubMed/NCBI E-utilities is used for biomedical publication retrieval. API keys are optional where supported, and tests use mocked HTTP responses rather than live network calls.

Optional environment variables:

```bash
POSTDOC_SCOUT_CONTACT_EMAIL="you@example.org"
NCBI_API_KEY="optional_ncbi_key"
```

Build queries, then collect publication evidence:

```bash
postdoc-scout build-queries --institution "Harvard University" --mode broad --output-dir outputs
postdoc-scout collect-evidence --query-file outputs/harvard_university_discovery_queries.json --sources openalex,pubmed --limit-per-source 20 --output-dir outputs
```

This writes:

```text
outputs/evidence_collection.json
outputs/evidence_collection.md
```

The evidence collection report includes connector summaries, query counts, publication counts before and after deduplication, top retrieved publications grouped by source and institution unit, retrieval warnings, and limitations.

Limitations:

- author disambiguation is not solved yet
- retrieved publications are evidence candidates, not verified supervisor profiles
- affiliation metadata may be incomplete
- results require later scoring and verification
- this layer does not scrape websites or implement full supervisor ranking

## Author Extraction and Candidate Clustering

Author extraction runs after evidence collection because it needs normalized publication records with authors, affiliations, query IDs, evidence IDs, and relevance domains. It turns publication-level evidence into preliminary author mentions, then conservatively clusters repeated mentions into possible supervisor candidates.

The extractor uses ordered author lists to infer first, middle, and last-author positions. Last, corresponding, and senior-style mentions are prioritized because translational biomedical labs are often represented by senior or corresponding authors on clinically relevant publications. Repeated appearances across relevant publications and affiliation overlap with matched institution units increase preliminary confidence.

Candidate identity remains preliminary. The extractor does not solve author disambiguation, does not verify employment or supervisor status, and does not merge identities aggressively when affiliation metadata is missing or inconsistent. Ambiguity warnings are preserved in JSON, Markdown, and CSV outputs.

Evidence traceability is preserved through publication titles, source connectors, originating query IDs, matched institution units, relevance domains, and evidence IDs.

Run:

```bash
postdoc-scout extract-candidates --evidence-file outputs/evidence_collection.json --institution "Harvard University" --mode broad --output-dir outputs
```

This writes:

```text
outputs/candidate_extraction.json
outputs/candidate_extraction.md
outputs/candidate_extraction.csv
```

This is candidate discovery, not final supervisor ranking.

## Candidate Ranking Report

Candidate ranking converts preliminary `CandidateCluster` outputs into scoreable `SupervisorCandidate` records, applies the deterministic scoring framework, and writes an auditable ranked supervisor report. It connects author-cluster evidence to the same score dimensions used by mock candidate scoring.

Scoring is evidence-based and traceable. The ranker infers domains from publication relevance domains, query-derived evidence, matched institution units, journals, and evidence notes. It preserves evidence IDs, ambiguity warnings, method-heavy penalty status, score breakdowns, and limitations for every ranked candidate.

Rankings remain preliminary. Author identity is not verified, publication evidence is not a full CV, affiliation metadata may be incomplete, and the output requires human review before outreach. Method-heavy profiles are penalized when they lack clinical or digital medicine translation signals, while translational methods work can still score well.

Run:

```bash
postdoc-scout rank-candidates --candidate-file outputs/candidate_extraction.json --evidence-file outputs/evidence_collection.json --institution "Harvard University" --mode broad --output-dir outputs
```

This writes:

```text
outputs/ranked_supervisors.json
outputs/ranked_supervisors.md
outputs/ranked_supervisors.csv
```

## Candidate Profile Enrichment

Candidate profile enrichment runs after ranking so additional profile and funding evidence can annotate an already auditable ranked candidate list without changing the original score or rank. The enrichment layer preserves the original ranking fields and adds a clearly labeled preliminary enrichment-adjusted score.

NIH RePORTER is used to look for recent grant and project evidence by PI name and organization hints. Semantic Scholar is used for preliminary author profile evidence such as author IDs, affiliation strings, paper counts, citation counts, h-index, and fields of study. Profile matching is conservative: multiple matches, missing affiliations, and weak affiliation overlap are surfaced as warnings rather than treated as identity certainty.

Manual profile and opening evidence is currently a placeholder layer. The project does not scrape arbitrary lab websites yet, so opening signals require human review of lab pages, department pages, and institutional profiles before contacting any PI.

Run:

```bash
postdoc-scout enrich-candidates --ranked-file outputs/ranked_supervisors.json --sources nih_reporter,semantic_scholar,manual --output-dir outputs
```

This writes:

```text
outputs/enriched_supervisors.json
outputs/enriched_supervisors.md
outputs/enriched_supervisors.csv
```

Limitations:

- profile matches are preliminary
- NIH RePORTER may miss non-NIH funding
- Semantic Scholar author disambiguation can be incomplete
- lab openings are not fully scraped yet
- human review is required before contacting any PI

## End-to-End Pipeline

The full pipeline orchestrator runs the scouting workflow from institution mapping through query generation, publication evidence collection, candidate extraction, ranking, and optional candidate enrichment. It is designed to make every stage auditable and resumable, with structured stage status, warnings, metrics, and output paths.

Run a dry run first to inspect the ecosystem map and discovery queries without calling external APIs:

```bash
postdoc-scout run-pipeline --institution "Harvard University" --mode broad --country us --output-dir outputs/harvard --dry-run
```

Run the full pipeline:

```bash
postdoc-scout run-pipeline --institution "Harvard University" --mode broad --country us --output-dir outputs/harvard
```

Common controls:

- `--sources openalex,pubmed` selects publication evidence connectors.
- `--enrichment-sources nih_reporter,semantic_scholar,manual` selects enrichment sources.
- `--limit-queries`, `--limit-per-source`, and `--top-n` constrain runtime and output size.
- `--year-from` and `--year-to` bound publication and funding searches where supported.
- `--resume` reuses existing stage outputs when present; `--no-resume` overwrites them.
- `--skip-evidence-collection` reuses an existing `evidence_collection.json`.
- `--skip-enrichment` stops after ranked supervisor reports.
- `--format json|md|all` records the preferred pipeline report format while stage outputs remain auditable.

For `outputs/harvard`, the canonical outputs are:

```text
outputs/harvard/ecosystem.json
outputs/harvard/ecosystem.md
outputs/harvard/discovery_queries.json
outputs/harvard/discovery_queries.md
outputs/harvard/evidence_collection.json
outputs/harvard/evidence_collection.md
outputs/harvard/candidate_extraction.json
outputs/harvard/candidate_extraction.md
outputs/harvard/candidate_extraction.csv
outputs/harvard/ranked_supervisors.json
outputs/harvard/ranked_supervisors.md
outputs/harvard/ranked_supervisors.csv
outputs/harvard/enriched_supervisors.json
outputs/harvard/enriched_supervisors.md
outputs/harvard/enriched_supervisors.csv
outputs/harvard/pipeline_run.json
outputs/harvard/pipeline_summary.md
```

Demo workflow:

```bash
postdoc-scout run-pipeline --institution "Harvard University" --mode broad --country us --output-dir outputs/harvard --dry-run --limit-queries 20
postdoc-scout run-pipeline --institution "Harvard University" --mode broad --country us --output-dir outputs/harvard --limit-queries 20 --limit-per-source 5 --top-n 20
postdoc-scout run-pipeline --institution "Harvard University" --mode broad --country us --output-dir outputs/harvard --skip-enrichment
```

The pipeline does not scrape arbitrary lab websites or use private data. Candidate identity, institutional affiliation, lab openings, and supervisor suitability remain preliminary and require human review before outreach.

## Configuration

The `configs/` directory contains initial YAML configuration for:

- `journal_tiers.yml`: journal and venue tier placeholders
- `domain_keywords.yml`: positive and negative domain signals
- `scoring_weights.yml`: initial scoring dimensions and weights
- `institution_affiliates.yml`: curated institution ecosystem seed entries
- `us_institution_targets.yml`: U.S. university and academic medical center seed parents
- `us_institution_affiliates.yml`: U.S. cancer center, pediatric hospital, and health-system seed parents
- `us_independent_research_institutes.yml`: U.S. independent research institute seed parents

These files are intentionally simple so the project can evolve without hard-coded private assumptions.

## MVP Roadmap

1. Add source adapters for public faculty pages, publication metadata, and grant/project records.
2. Build candidate extraction for supervisors, affiliations, domains, and evidence links.
3. Implement configurable scoring for translational fit, disease-area relevance, clinical data depth, and mentorship signals.
4. Add audit reports with citations, uncertainty flags, and reasons for inclusion or exclusion.
5. Export ranked results to CSV, Markdown, and JSON for review.

## Development

```bash
pytest
ruff check .
```

## License

MIT
