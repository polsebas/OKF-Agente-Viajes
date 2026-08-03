---
name: okf-conformance-consult
description: >
  Quick reference for constructing conformant OKF frontmatter and links when
  creating or appending itinerary concepts. Consult this before calling
  create_concept or append_to_concept to reduce validation rejections. This
  is advisory only — the validation engine, not this skill, decides whether
  a write is accepted.
metadata:
  version: "1.0"
  scope: runtime consult, not dev-time authoring guidance
---

# OKF conformance — quick consult

Use this before calling a write tool, to increase the odds your first attempt
passes validation. **This does not grant permission to skip validation** —
create_concept and append_to_concept always run through the validation
engine regardless of whether you consulted this skill.

## Required
- `type` — non-empty string. For this vault: `day`, `flight`, `lodging`, or `note`.

## Recommended
- `title`, `tags` (list), `timestamp` (ISO 8601)

## Links
Use `[text](concept_id.md)`, bundle-relative. A link to a concept that
doesn't exist yet is permitted by OKF but surfaces as a warning — prefer
linking to concepts you've confirmed exist via query_okf_concept first.

## Tags
Check the tag-taxonomy-conventions skill before inventing a new tag — an
existing canonical tag likely already covers it.

## If a write is rejected anyway
Relay the exact validator error to the user per your constitution's Output
Contract. Do not retry more than once with a guessed fix.
