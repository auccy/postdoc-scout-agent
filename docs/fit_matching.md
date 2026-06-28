# CV-to-PI Fit Matching

CV-to-PI fit matching compares a user-supplied research profile YAML with ranked
or enriched supervisor candidates. It is deterministic, auditable, and based
only on provided profile terms plus candidate evidence already present in the
pipeline outputs.

Run:

```bash
postdoc-scout match-fit --ranked-file outputs/enriched_supervisors.json --user-profile examples/user_profile.example.yml --output-dir outputs --format all
```

This writes:

```text
outputs/fit_assessments.json
outputs/fit_assessments.md
outputs/fit_assessments.csv
```

## User Profile YAML

Start from `examples/user_profile.example.yml`. The profile includes preferred
domains, secondary domains, methods, datasets, disease areas, translational
strengths, avoid directions, preferred geographies, and preferred institution
types.

Avoid directions are used as deterministic risk checks for profile mismatch:

```yaml
avoid_directions:
  pure_statistical_theory: true
  pure_algorithm_architecture: true
  wet_lab_only: true
  clinical_fellowship_only: true
```

## Fit Dimensions

The matcher scores:

- `domain_fit`
- `data_fit`
- `translational_fit`
- `disease_fit`
- `method_fit`
- `opportunity_fit`
- `mismatch_risk`

Method fit has a lower weight than domain, data, translational, and disease fit.
This keeps the ranking aligned with translational digital medicine and clinical
AI rather than pure methods matching.

## Limitations

Fit matching does not call external APIs, scrape lab websites, generate messages,
or infer candidate facts that are not in the input evidence. Opening signals are
used only if they already exist in an enrichment file or sibling
`opening_signals.json` report.

The output is a triage aid. Human review is required to verify current role,
affiliation, recent publications, lab activity, mentorship environment, funding
fit, and whether the candidate has postdoctoral capacity.
