# U.S. Curated Seed Map

The U.S. seed map is a conservative research ecosystem map for postdoctoral supervisor scouting. It is not a legal affiliation database.

## Scope

The seed map includes parent institutions and units across:

- universities and academic medical centers
- cancer centers
- pediatric hospitals
- health systems
- independent biomedical research institutes
- public health and biomedical informatics ecosystems

The purpose is to make discovery broader than a single university department, because translational digital medicine and clinical AI labs often sit in medical schools, hospitals, cancer centers, public health schools, or nearby partner institutes.

## Validation

Run:

```bash
postdoc-scout validate-seed-map --country us --output-dir outputs
```

The validator checks required fields, controlled relationship labels, duplicate names, list-shaped domains and URLs, unsupported relevance domains, and relationship warnings.

Relationship warnings do not necessarily indicate bad entries. They flag cases where a relationship label is useful for scouting but still requires future automated verification.

## Extension Guidelines

- Prefer conservative relationship labels.
- Include `source_urls` as a list, even when empty.
- Keep aliases as lists.
- Use controlled relevance domains.
- Do not remove seed entries unless they are clearly duplicated or invalid.
- Treat all seed entries as needing verification until automated checks exist.

