---
name: tag-taxonomy-conventions
description: >
  Canonical tags and hierarchy for this itinerary vault, so the agent reuses
  existing tags instead of creating near-duplicate synonyms. Consult before
  tagging a new or appended concept. The reference snapshot is regenerated
  automatically by the maintenance cron — never edit it by hand.
metadata:
  version: "1.0"
  generated_by: core/maintenance_cron.py::regenerate_taxonomy_snapshot
---

# Tag taxonomy conventions

Before adding a tag to a concept, check references/taxonomy-snapshot.md for
the current canonical list and hierarchy. If the concept you're tagging
clearly matches an existing canonical tag or one of its aliases, use the
canonical form.

If nothing fits, it's fine to use a new tag — do not block a write over
tagging uncertainty. New tags get triaged by the maintenance cron's
canonicalization pass, not by you. You are never the one applying a tag
merge, regardless of what this skill says.

## Reference
references/taxonomy-snapshot.md is regenerated after every successful
apply_tag_rewrite. Read it fresh each time — don't assume yesterday's tags
are still current if the cron ran overnight.
