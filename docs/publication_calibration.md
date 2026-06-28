# Journal / Authorship Calibration

Publication calibration improves candidate ranking by reducing reliance on raw publication counts. It is deterministic, configurable, and does not use live impact factors.

## Why Publication Count Alone Is Insufficient

Raw counts can inflate profiles with:

- middle-author consortium papers where contribution is unclear
- old high-impact publications without recent translational output
- method-heavy work without clinical or disease-domain evidence
- many low-relevance papers in adjacent computational venues

The calibration layer scores each publication using journal basket, author position, recency, domain relevance, article type, and warnings.

## Journal Baskets

Configured baskets live in `configs/journal_tiers.yml`. They include:

- top general medical journals
- Science/Nature/Cell tier journals
- flagship subjournals
- AD/neurology field-leading journals
- digital medicine and biomedical informatics journals
- oncology journals
- public health journals
- method-heavy venues that are downweighted when pure

These baskets are scouting heuristics, not claims about live journal impact factors.

## Authorship Weighting

Senior, corresponding, and last-author positions are weighted most strongly because the project is scouting potential supervisors. First and co-first roles remain valuable but are less supervisor-specific. Middle-author roles are downweighted to avoid publication-count inflation.

## Recency and Article Type

Recent clinically relevant work receives higher weight than old isolated impact. Clinical trials, cohorts, registry studies, prediction studies, and clinical decision support work receive stronger article-type weights than editorials, letters, or generic reviews.

## Method-Heavy Handling

Method-heavy journals and venues such as statistical theory or benchmark-focused machine learning venues are not excluded. They are treated conservatively when there is no explicit clinical translation, disease relevance, EHR/RWD, patient stratification, or implementation-facing signal.

## CLI

```bash
postdoc-scout calibrate-publications --ranked-file outputs/ranked_supervisors.json --output-dir outputs --format all
```

Outputs:

```text
outputs/publication_calibration.json
outputs/publication_calibration.md
outputs/publication_calibration.csv
```

The Markdown report includes journal-tier summaries, author-position summaries, candidate-level calibrated impact, warnings, and an explanation of why calibrated scores differ from raw counts.

