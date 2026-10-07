from __future__ import annotations

from cleaner_core.contracts import Finding
from cleaner_core.document_regions import scan_all_document_regions


TEST_META = {
    "id": "DOCUMENT_BOUNDARIES",
    "title": "Document Boundary Check",
    "kind": "test",
    "profile_rule": "data_model.document_boundaries",
    "snapshot_mode": "openpyxl",
}


def run(snapshot, profile, log):
    log(
        "START",
        "DOCUMENT_BOUNDARIES derives logical document row regions from mapped "
        "identifier anchors and their merge geometry.",
    )

    scans = scan_all_document_regions(snapshot, profile)
    findings: list[Finding] = []

    for sheet, scan in scans.items():
        if any(x.get("kind") == "SHEET_NOT_FOUND" for x in scan.ambiguities):
            message = f"{sheet}: sheet not found; boundary detection skipped."
            log("PROFILE_MISMATCH", message)
            findings.append(Finding(
                test_id="DOCUMENT_BOUNDARIES",
                status="PROFILE_MISMATCH",
                severity="CRITICAL",
                sheet=sheet,
                message=message,
                evidence=scan.to_dict(),
            ))
            continue

        log(
            "SUMMARY",
            f"{sheet}: document regions={len(scan.regions)}, "
            f"excluded separator/background ranges={len(scan.excluded_separator_ranges)}, "
            f"ambiguities={len(scan.ambiguities)}.",
        )

        if scan.excluded_separator_ranges:
            log(
                "INFO",
                f"{sheet}: excluded separator/background ranges: "
                + ", ".join(scan.excluded_separator_ranges),
            )

        for ambiguity in scan.ambiguities:
            if ambiguity.get("kind") == "PROFILE_MAPPING":
                status = "PROFILE_MISMATCH"
                severity = "CRITICAL"
                target = None
            else:
                status = "FAIL"
                severity = "HIGH"
                target = ambiguity.get("target") or str(ambiguity.get("row") or "")

            message = ambiguity.get("message") or (
                f"{sheet}: ambiguous document boundary at {target}."
            )
            log(status, message)
            findings.append(Finding(
                test_id="DOCUMENT_BOUNDARIES",
                status=status,
                severity=severity,
                sheet=sheet,
                target=target or None,
                message=message,
                expected="Unambiguous logical document row region",
                observed=ambiguity.get("reasons") or ambiguity,
                evidence=ambiguity,
            ))

    log(
        "DONE",
        f"DOCUMENT_BOUNDARIES finished with {len(findings)} review finding(s).",
    )
    return findings
