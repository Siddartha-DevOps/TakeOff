"""Validate rights, provenance, privacy, integrity, and leakage before annotation."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, UnidentifiedImageError


ALLOWED_PERMISSION_BASES = {"owned", "customer_consent", "written_license", "contract_data_terms"}
ALLOWED_DRAWING_TYPES = {
    "residential_single_family", "apartment_multi_unit", "commercial_retail",
    "office", "hospitality", "other",
}
ALLOWED_DISCIPLINES = {
    "architectural_floor_plan", "architectural_reflected_ceiling", "structural", "mep", "other",
}
BLOCKER_KEYS = (
    "rights", "provenance", "deidentification", "duplicate", "corrupted", "project_leakage_risk",
)


@dataclass
class SheetIntakeResult:
    sample_id: str
    project_id: str
    status: str
    blockers: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class IntakeAudit:
    ready_for_annotation: bool
    counts: dict[str, int]
    blockers: dict[str, int]
    sheets: list[SheetIntakeResult]

    def as_dict(self) -> dict:
        return {
            "ready_for_annotation": self.ready_for_annotation,
            "counts": self.counts,
            "blockers": self.blockers,
            "sheets": [asdict(sheet) for sheet in self.sheets],
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity_error(path: Path) -> str | None:
    if not path.is_file():
        return "eligible file is missing"
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            with path.open("rb") as handle:
                prefix = handle.read(5)
                handle.seek(max(0, path.stat().st_size - 2048))
                tail = handle.read()
            if prefix != b"%PDF-" or b"%%EOF" not in tail:
                return "PDF header or end marker is invalid"
            try:
                import fitz  # type: ignore

                with fitz.open(path) as document:
                    if document.page_count < 1:
                        return "PDF has no pages"
            except ImportError:
                pass
            except Exception as exc:  # pragma: no cover - library error text is environment-specific
                return f"PDF cannot be parsed: {exc}"
        except OSError as exc:
            return f"PDF cannot be read: {exc}"
        return None
    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        return f"image cannot be parsed: {exc}"
    return None


def _nonempty(sample: dict, field_name: str) -> bool:
    return bool(str(sample.get(field_name, "")).strip())


def validate_intake_manifest(manifest_path: str | Path, source_root: str | Path) -> IntakeAudit:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    root = Path(source_root).resolve()
    samples = manifest.get("samples", [])
    results: list[SheetIntakeResult] = []
    hashes: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    project_splits: dict[str, set[str]] = defaultdict(set)
    project_owners: dict[str, set[str]] = defaultdict(set)

    for sample in samples:
        sample_id = str(sample.get("sample_id", "")).strip() or "<missing>"
        project_id = str(sample.get("project_id", "")).strip()
        blockers: dict[str, list[str]] = {key: [] for key in BLOCKER_KEYS}

        rights = sample.get("rights", {})
        if sample.get("permission_basis") not in ALLOWED_PERMISSION_BASES:
            blockers["rights"].append("permission basis is missing or unsupported")
        if sample.get("commercial_ml_training_allowed") is not True:
            blockers["rights"].append("commercial ML training is not explicitly allowed")
        for name in ("source_owner", "permission_basis"):
            if not _nonempty(sample, name):
                blockers["rights"].append(f"{name} is required")
        if not (
            rights.get("status") == "approved"
            and str(rights.get("evidence_ref", "")).strip()
            and str(rights.get("verified_by", "")).strip()
            and rights.get("verified_at")
        ):
            blockers["rights"].append("rights approval, evidence, verifier, and timestamp are required")

        provenance = sample.get("provenance", {})
        required_provenance = (
            "project_id", "drawing_type", "discipline", "revision", "page_sheet_number",
            "source_file_sha256", "eligible_file_sha256", "source_path", "eligible_path", "intake_date",
        )
        if any(not _nonempty(sample, name) for name in required_provenance):
            blockers["provenance"].append("one or more mandatory sheet provenance fields are missing")
        if sample.get("drawing_type") not in ALLOWED_DRAWING_TYPES:
            blockers["provenance"].append("drawing_type is invalid")
        if sample.get("discipline") not in ALLOWED_DISCIPLINES:
            blockers["provenance"].append("discipline is invalid")
        if not (
            provenance.get("status") == "recorded"
            and str(provenance.get("source_reference", "")).strip()
            and str(provenance.get("recorded_by", "")).strip()
            and provenance.get("recorded_at")
        ):
            blockers["provenance"].append("recorded source reference, recorder, and timestamp are required")

        deidentification = sample.get("deidentification", {})
        required = sample.get("deidentification_required") is True
        expected_status = "complete" if required else "not_required"
        if sample.get("deidentification_status") != expected_status:
            blockers["deidentification"].append(f"status must be {expected_status}")
        if required:
            if not (
                str(deidentification.get("performed_by", "")).strip()
                and str(deidentification.get("reviewed_by", "")).strip()
                and deidentification.get("completed_at")
                and str(deidentification.get("redaction_log_ref", "")).strip()
                and deidentification.get("geometry_preserved") is True
            ):
                blockers["deidentification"].append(
                    "completed redaction log, performer, independent reviewer, timestamp, and geometry approval are required"
                )
            if sample.get("source_file_sha256") == sample.get("eligible_file_sha256"):
                blockers["deidentification"].append("required de-identification must produce a separately hashed derivative")

        eligible_path = (root / str(sample.get("eligible_path", ""))).resolve()
        if root not in eligible_path.parents:
            blockers["corrupted"].append("eligible path escapes source root")
        else:
            integrity_error = _integrity_error(eligible_path)
            if integrity_error:
                blockers["corrupted"].append(integrity_error)
            else:
                actual_hash = _sha256(eligible_path)
                if actual_hash != sample.get("eligible_file_sha256"):
                    blockers["corrupted"].append("eligible file SHA-256 does not match manifest")
                hashes[actual_hash].append((sample_id, project_id, str(sample.get("page_sheet_number", ""))))
        integrity = sample.get("file_integrity", {})
        if integrity.get("status") != "passed" or not integrity.get("verified_at"):
            blockers["corrupted"].append("file integrity approval and timestamp are required")

        if not project_id:
            blockers["project_leakage_risk"].append("project identity is unknown")
        else:
            requested_split = sample.get("requested_split")
            if requested_split:
                project_splits[project_id].add(requested_split)
            project_owners[project_id].add(str(sample.get("source_owner", "")).strip())

        results.append(SheetIntakeResult(sample_id, project_id, "pending", blockers))

    result_by_id = {result.sample_id: result for result in results}
    for digest, occurrences in hashes.items():
        projects = {project_id for _, project_id, _ in occurrences}
        pages = {(project_id, page_number) for _, project_id, page_number in occurrences}
        if len(projects) > 1 or len(pages) < len(occurrences):
            for sample_id, _project_id, _page in occurrences:
                result_by_id[sample_id].blockers["duplicate"].append(
                    f"file hash {digest} is duplicated across a project or page identity"
                )
                if len(projects) > 1:
                    result_by_id[sample_id].blockers["project_leakage_risk"].append(
                        "identical file is assigned to multiple project identities"
                    )
    for project_id, splits in project_splits.items():
        if len(splits) > 1:
            for result in results:
                if result.project_id == project_id:
                    result.blockers["project_leakage_risk"].append(
                        f"project has conflicting requested splits: {sorted(splits)}"
                    )
    for project_id, owners in project_owners.items():
        owners.discard("")
        if len(owners) > 1:
            for result in results:
                if result.project_id == project_id:
                    result.blockers["project_leakage_risk"].append(
                        "project identity is associated with multiple source owners"
                    )

    category_counts = Counter()
    for result in results:
        result.blockers = {key: value for key, value in result.blockers.items() if value}
        for key in result.blockers:
            category_counts[key] += 1
        result.status = "blocked" if result.blockers else "eligible"

    counts = {
        "received": len(samples),
        "eligible": sum(result.status == "eligible" for result in results),
        "rights_cleared": sum("rights" not in result.blockers for result in results),
        "provenance_recorded": sum("provenance" not in result.blockers for result in results),
        "deidentified": sum("deidentification" not in result.blockers for result in results),
        "integrity_passed": sum("corrupted" not in result.blockers for result in results),
        "annotated": sum(sample.get("annotation", {}).get("status") in {"complete", "approved"} for sample in samples),
        "reviewed": sum(bool(sample.get("annotation", {}).get("reviewers")) for sample in samples),
        "accepted": sum(sample.get("annotation", {}).get("status") == "approved" for sample in samples),
    }
    return IntakeAudit(
        ready_for_annotation=bool(samples) and counts["eligible"] == len(samples),
        counts=counts,
        blockers={key: category_counts[key] for key in BLOCKER_KEYS},
        sheets=results,
    )


def write_eligible_manifest(manifest_path: Path, report_path: Path, output_path: Path, audit: IntakeAudit) -> None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_id = {result.sample_id: result for result in audit.sheets}
    validated_at = datetime.now(timezone.utc).isoformat()
    for sample in payload.get("samples", []):
        result = by_id[str(sample.get("sample_id", "")).strip() or "<missing>"]
        sample["intake_eligibility"] = {
            "status": result.status,
            "validated_at": validated_at,
            "report_ref": str(report_path),
        }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--eligible-manifest-out", type=Path)
    args = parser.parse_args(argv)
    audit = validate_intake_manifest(args.manifest, args.source_root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(audit.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.eligible_manifest_out:
        write_eligible_manifest(args.manifest, args.report, args.eligible_manifest_out, audit)
    print(json.dumps(audit.as_dict(), indent=2, sort_keys=True))
    return 0 if audit.ready_for_annotation else 2


if __name__ == "__main__":
    raise SystemExit(main())
