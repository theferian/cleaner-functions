from __future__ import annotations

from cleaner_core.contracts import Finding
from cleaner_core.document_structure import (
    document_structure_config,
    scan_all_document_structures,
)


TEST_META = {
    "id": "DOCUMENT_STRUCTURE",
    "title": "Document Structure Check",
    "kind": "test",
    "profile_rule": "data_model.document_structure",
    "snapshot_mode": "openpyxl",
}


def run(snapshot, profile, log):
    config = document_structure_config(profile)
    log(
        "START",
        "DOCUMENT_STRUCTURE fingerprints each derived DocumentRegion using normalized "
        "merge geometry. Row positions are excluded so valid cards may move between weeks.",
    )

    scans = scan_all_document_structures(snapshot, profile)
    findings: list[Finding] = []

    for sheet, scan in scans.items():
        known_count = sum(1 for x in scan.patterns.values() if x.get("known"))
        unknown = [x for x in scan.patterns.values() if not x.get("known")]

        log(
            "SUMMARY",
            f"{sheet}: document regions={len(scan.regions)}, "
            f"structure patterns={len(scan.patterns)}, known patterns={known_count}, "
            f"unknown patterns={len(unknown)}, hazards={len(scan.hazards)}.",
        )

        for pattern_id, bucket in sorted(scan.patterns.items()):
            state = "KNOWN" if bucket.get("known") else "UNKNOWN"
            log(
                "INFO",
                f"{sheet}: {pattern_id} count={bucket['count']} state={state}; "
                f"examples={', '.join(bucket['targets'][:5])}",
            )

        for hazard in scan.hazards:
            message = hazard["message"]
            log("FAIL", message)
            findings.append(Finding(
                test_id="DOCUMENT_STRUCTURE",
                status="FAIL",
                severity="HIGH",
                sheet=sheet,
                target=hazard.get("target"),
                message=message,
                expected="Merged ranges contained within one derived DocumentRegion",
                observed=hazard.get("ranges"),
                evidence=hazard,
            ))

        # Unknown patterns are reviewed once per unique geometry, not once per
        # physical document. ACCEPT_EXCEPTION means "this geometry is a valid
        # structure pattern" and can then be promoted into profile knowledge.
        for bucket in unknown:
            pattern = bucket["pattern"]
            targets = list(bucket["targets"])
            representative = targets[0] if targets else None
            message = (
                f"{sheet}: unlearned document structure pattern "
                f"{pattern['pattern_id']} appears in {bucket['count']} region(s). "
                "Review the geometry once; if valid, ACCEPT_EXCEPTION and promote "
                "the decision so future weekly files recognize it automatically."
            )
            log(config["unknown_pattern_status"], message)
            findings.append(Finding(
                test_id="DOCUMENT_STRUCTURE",
                status=config["unknown_pattern_status"],
                severity="MEDIUM",
                sheet=sheet,
                target=representative,
                message=message,
                expected="Structure pattern already learned by the AZD profile",
                observed=pattern,
                evidence={
                    "structure_pattern": pattern,
                    "pattern_count": bucket["count"],
                    "representative_targets": targets[:20],
                    "all_targets": targets,
                },
                suggested_exception={
                    "kind": "LEARN_STRUCTURE_PATTERN",
                    "sheet": sheet,
                    "pattern_id": pattern["pattern_id"],
                },
            ))

    log(
        "DONE",
        f"DOCUMENT_STRUCTURE finished with {len(findings)} review finding(s).",
    )
    return findings
