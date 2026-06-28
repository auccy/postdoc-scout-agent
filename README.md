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
