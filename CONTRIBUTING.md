# Contributing

Thank you for considering a contribution to Postdoc Scout Agent. The project is early-stage research software, so contributions should keep outputs deterministic, auditable, and honest about uncertainty.

## Setup

```bash
pip install -e ".[dev]"
```

## Checks

```bash
pytest
ruff check .
```

Tests must not call external APIs, scrape websites, or require private credentials.

## Adding Seed-Map Entries

- Add entries to the relevant file in `configs/`.
- Keep `canonical_name` non-empty.
- Use lists for `aliases`, `relevance_domains`, `units`, and `source_urls`.
- Use conservative relationship labels.
- Keep `verification_status` explicit.
- Run:

```bash
postdoc-scout validate-seed-map --country us --output-dir outputs
```

The seed map is a research ecosystem map, not a legal affiliation database.

## Adding Connectors

- Put connector code under `src/postdoc_scout/connectors/`.
- Normalize external records into shared Pydantic models.
- Preserve source IDs, URLs, query IDs, and warnings.
- Add mocked tests with `httpx.MockTransport` or equivalent fixtures.
- Do not add tests that depend on live network access.

## Keeping Evidence Auditable

Every generated report should preserve:

- source name
- source identifier or URL when available
- originating query or input file
- relevance domains
- warnings and limitations
- evidence IDs that can be traced through ranking

Prefer warnings over silent assumptions.

## Style

- Keep modules focused and small enough to test.
- Prefer deterministic transformations over hidden state.
- Use Pydantic models for structured outputs.
- Keep CLI commands explicit and documented.
- Use `ruff check .` before opening a PR.

## Ethical Use

Do not add features that make unverified claims about individual researchers. Human review must remain part of the workflow before outreach, applications, or public reporting.

