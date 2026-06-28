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

## Configuration

The `configs/` directory contains initial YAML configuration for:

- `journal_tiers.yml`: journal and venue tier placeholders
- `domain_keywords.yml`: positive and negative domain signals
- `scoring_weights.yml`: initial scoring dimensions and weights

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
