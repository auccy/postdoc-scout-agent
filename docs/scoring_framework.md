# Scoring Framework

The scoring framework ranks preliminary supervisor candidates using explicit evidence, not hidden heuristics. Each score includes dimensions, weights, explanations, warnings, and supporting evidence IDs.

## Positive Signals

- Translational digital medicine and clinical AI fit.
- AD/ADRD, oncology, public health, and other disease-domain relevance.
- EHR/RWD, cohorts, registries, clinical trials, and clinical data infrastructure.
- Patient stratification, risk prediction, progression modeling, and clinical decision support.
- Recent publication evidence in relevant venues.
- Structured profile, funding, or manual opening-signal evidence.

## Method-Heavy Penalty

The project applies a modest penalty when evidence is dominated by pure statistical theory, benchmark-only machine learning, simulation-only studies, optimization theory, or foundation model architecture without clear clinical translation.

The penalty is not a hard exclusion. A candidate with strong methods work can still rank well if there is evidence of clinical data use, disease applications, implementation-facing work, or translational digital medicine.

## Audit Trail

Ranking outputs preserve:

- inferred domains
- publication and evidence IDs
- score dimensions and weighted contributions
- method-heavy penalty status
- ambiguity warnings
- limitations and suggested manual checks

The output is intended for evidence triage. It should not be treated as a verified claim about identity, availability, mentorship quality, or lab openings.

