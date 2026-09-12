# AEC drawing de-identification workflow

## Safety rule

De-identification creates a derivative; it never edits or replaces the restricted original. Preserve walls, openings, room boundaries, room labels needed for the seven-class task, dimensions, scale graphics, sheet geometry, and drawing resolution. Redact only identifying/confidential content. Record the original and derivative hashes and retain a reviewer-approved redaction log.

## Required review regions

- client/owner names and logos;
- project names, job numbers, and internal project codes;
- street/site addresses, parcel identifiers, coordinates, and location maps when identifying;
- phone numbers, email addresses, signatures, stamps, and personal identifiers;
- architect, engineer, consultant, contractor, and developer names/logos when the permission terms require removal;
- title-block confidential, bid, contract, issue, and distribution metadata;
- revision notes or markups containing names, claims, prices, schedules, access/security details, or other sensitive information;
- QR codes, barcodes, hyperlinks, metadata, PDF attachments, comments, layers, and document properties that can reveal the source.

Do not remove generic room names, dimensional geometry, scale text/bars, north arrows, grids, section/elevation markers, or non-identifying revision geometry needed to understand the plan.

## Process

1. **Classify restrictions:** read the permission evidence and confidentiality terms; set `deidentification_required` and a redaction scope.
2. **Inventory content:** inspect every page visually and inspect PDF metadata, attachments, annotations, layers, and OCR text. Raster scans still require visual/OCR review.
3. **Create derivative:** use true redaction that removes underlying text/vector objects, not a translucent or removable overlay. Rasterize only when necessary and at a resolution that preserves room geometry.
4. **Sanitize metadata:** remove document properties, embedded files, comments, hidden layers, links, and recoverable redaction content.
5. **Geometry QA:** compare the derivative with the original. Confirm wall/room geometry, dimensions, scale, page size, crop, and resolution remain usable and unchanged outside approved redaction regions.
6. **Privacy QA:** OCR/search the derivative for every known client/project/address/contact token and inspect title blocks and revision notes manually.
7. **Independent approval:** a second reviewer verifies privacy and geometry, records redaction categories and exceptions, and sets `deidentification_status=complete`.
8. **Hash and isolate:** compute `eligible_file_sha256`; store the derivative in restricted dataset staging and the original in separate restricted evidence storage.

## Failure and withdrawal

If identity cannot be removed without destroying training geometry, reject the sheet. If permission is withdrawn or expires, mark rights rejected/expired, quarantine every derivative/annotation, remove it from future dataset versions, and preserve only the minimum audit record required by policy.
