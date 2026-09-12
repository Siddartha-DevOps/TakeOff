# Source intake checklist — in-domain room/space sheets

Use one record per incoming sheet/page and one stable opaque `project_id` for every page, revision, and set belonging to the same real project. Do not place a file in train, validation, test, or golden storage until the intake validator reports it eligible. Intake eligibility does not mean annotation acceptance.

## What the provider must supply

- [ ] Source/owner legal name and provider contact.
- [ ] Permission basis: owned, explicit customer consent, written license, or applicable contract data terms.
- [ ] Commercial ML training allowed: **YES/NO**. A missing or qualified answer is NO until legal review approves it.
- [ ] Redistribution allowed: **YES/NO**. This controls dataset/artifact sharing and is independent of permission to train.
- [ ] Evidence reference to the signed agreement, consent, license, or approved data terms. Store the evidence in the restricted rights register, not in the dataset directory.
- [ ] Confidentiality restrictions, retention requirements, permitted personnel, geography, and deletion/withdrawal terms.
- [ ] Whether de-identification is required and the required fields/redaction standard.
- [ ] Stable opaque project ID shared by all pages, revisions, and related sets.
- [ ] Drawing/building type: residential single-family, apartment/multi-unit, commercial/retail, office, hospitality, or reviewed other.
- [ ] Discipline: architectural floor plan preferred; record other disciplines rather than guessing.
- [ ] Revision/date designation.
- [ ] Page/sheet number.
- [ ] Original filename, source-relative path, byte size, MIME type, and SHA-256 hash.
- [ ] Intake date in ISO `YYYY-MM-DD` form.
- [ ] Provenance reference identifying how and from whom the exact file was received.

## Internal intake actions

1. Assign `sample_id` and opaque `project_id`; never derive either from a client name or address.
2. Store the untouched original in restricted, access-logged storage. Compute `source_file_sha256` immediately.
3. Verify rights and provenance independently; record reviewer and timestamps.
4. Produce a separate de-identified derivative when required. Never overwrite the original.
5. Compute `eligible_file_sha256` on the exact derivative proposed for annotation.
6. Run `validate_in_domain_intake.py`. Resolve every blocker before annotation handoff.
7. Only after intake eligibility, move the derivative to the annotation staging area. Split assignment happens later at project level after annotation acceptance.

## Eligibility decision

The sheet is **eligible for annotation intake** only when all are true:

- rights status is approved with evidence, and commercial ML training is explicitly allowed;
- provenance is recorded with a known source owner and exact source reference;
- project identity is known and consistent across related pages/revisions;
- de-identification is complete when required, with a separately hashed derivative;
- the eligible file exists, opens successfully, and matches its SHA-256;
- it is not an exact duplicate; any perceptual duplicate or conflicting project/split identity is resolved.

Redistribution may be NO while training is allowed. Such sheets remain restricted and must never be placed in a public dataset or model-demo repository.
