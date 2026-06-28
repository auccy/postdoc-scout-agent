# Streamlit Dashboard

The Streamlit dashboard is a lightweight interactive layer over the existing CLI pipeline. It is designed for demos, portfolio review, and quick exploration without turning the project into a web application with authentication or persistence.

## Install

```bash
pip install -e ".[dashboard]"
```

## Run

```bash
streamlit run app.py
```

## What It Supports

- Institution text input.
- Country and mode selectors.
- Output directory selection.
- Institution ecosystem mapping.
- Discovery query generation.
- Dry-run pipeline execution.
- Existing Markdown report viewer.
- Mock candidate scoring table and score breakdown.
- Download buttons for generated JSON, Markdown, and CSV outputs.

## Demo Workflow

1. Start Streamlit:

```bash
streamlit run app.py
```

2. Enter `Harvard University`.
3. Choose `broad` mode.
4. Choose an output directory such as `outputs/harvard_dry_run`.
5. Click **Run dry pipeline**.
6. Inspect the ecosystem map.
7. Inspect generated discovery queries by source.
8. Open the mock candidate scoring demo.
9. Use the export tab to download generated reports.

## Safety Defaults

- No external APIs are called on page load.
- Dry-run mode is the default.
- Full pipeline mode is explicitly marked as API-dependent.
- No authentication, database persistence, website scraping, or LLM summarization is included.
- All candidate outputs are preliminary and require human verification before outreach.

## Screenshot Placeholders

Screenshots are not generated in this initial dashboard PR. Suggested future screenshots:

- Header and sidebar controls.
- Ecosystem table after dry-run mapping.
- Discovery query source expanders.
- Mock candidate scoring table.
- Existing report viewer.

