# Demo Discovery Queries

Mock/demo data only. These examples illustrate query shape and audit fields.

## Top Queries

| Query ID | Source | Unit | Query |
| --- | --- | --- | --- |
| q_0001_pubmed | pubmed | Harvard Medical School | `("Harvard Medical School"[Affiliation]) AND ("clinical AI" OR "EHR/RWD" OR "digital medicine") AND ("prediction" OR "clinical decision support")` |
| q_0002_openalex | openalex | Dana-Farber Cancer Institute | `"Dana-Farber Cancer Institute" "oncology" "digital medicine"` |
| q_0003_pubmed | pubmed | Massachusetts General Hospital | `("Massachusetts General Hospital"[Affiliation]) AND ("real-world data" OR "clinical AI") AND ("risk prediction" OR "implementation")` |

## Rationale

Queries combine institution units, translational domains, and clinical application terms. They are generated before evidence collection so the search strategy can be inspected.

