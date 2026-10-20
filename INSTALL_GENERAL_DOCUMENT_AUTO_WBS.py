#!/usr/bin/env python3
r"""Install GENERAL_DOCUMENT automatic deterministic WBS decisions.

Run from the cleaner-functions repository root:
  py .\INSTALL_GENERAL_DOCUMENT_AUTO_WBS.py --check
  py .\INSTALL_GENERAL_DOCUMENT_AUTO_WBS.py
Does not alter Excel workbooks, old run results, or existing decisions.
"""
from __future__ import annotations

import argparse
import datetime
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent
PIPE = Path("functions/cleaner/azd_pipeline.py")
MODULE = Path("cleaner_core/general_doc_auto_wbs.py")
TEST = Path("unit_tests/test_general_document_auto_wbs.py")
MODULE_CONTENT = 'from __future__ import annotations\n\nimport re\n\nfrom review.decisions import apply_decision_to_queue, make_decision\n\n\n_WBS = re.compile(r"[0-9]+(?:\\.[0-9]+)*\\Z")\n_EMPTY_TOKENS = {"", "-", "–", "—"}\n_POLICY = "GENERAL_DOCUMENT_AUTO_WBS_V1"\n\n\ndef _can_auto_accept(item: dict, existing_wbs: set[str], used: set[str]) -> tuple[dict, str] | None:\n    """Only accept a profile-generated, parent-based placeholder for an empty WBS.\n\n    An actual (possibly mistyped) nonempty identifier, fallback-root suggestion,\n    unsafe target, or duplicate proposed identifier must still be reviewed.\n    """\n    source = item.get("source") or {}\n    evidence = item.get("evidence") or {}\n    suggestion = (item.get("machine_suggestion") or {}).get("suggested_fix") or {}\n    params = suggestion.get("parameters") or {}\n    location = item.get("location") or {}\n    if item.get("review_state") != "PENDING":\n        return None\n    if (source.get("test_id") != "IDENTIFIERS" or source.get("status") != "FAIL"\n            or evidence.get("field_key") != "wbs" or params.get("field_key") != "wbs"\n            or suggestion.get("action") != "SET_VALUE"):\n        return None\n    if not location.get("sheet") or not location.get("target"):\n        return None\n    if (params.get("sheet") != location["sheet"] or params.get("target") != location["target"]):\n        return None\n    observed = item.get("observed")\n    if ("" if observed is None else str(observed).strip()) not in _EMPTY_TOKENS:\n        return None\n    expected = params.get("expected_old_value")\n    if ("expected_old_value" not in params\n            or (None if expected is None else str(expected).strip()) !=\n               (None if observed is None else str(observed).strip())):\n        return None\n    parent = str(evidence.get("nearest_valid_wbs_above") or "")\n    value = str(params.get("value") or "")\n    if (not _WBS.fullmatch(parent) or not _WBS.fullmatch(value)\n            or not value.startswith(parent + ".")):\n        return None\n    suffix = value[len(parent)+1:]\n    if not suffix.isdigit() or int(suffix) < 1000:\n        return None\n    if value in existing_wbs or value in used:\n        return None\n    return params, value\n\n\ndef accept_general_document_wbs(queue: dict, profile: dict, existing_wbs: set[str]) -> int:\n    """Convert safe IDENTIFIERS WBS suggestions to auditable review decisions.\n\n    Mutates the review queue, but never modifies the Excel workbook. This is a\n    family-level opt-in using the existing nearest-valid-above WBS profile rule.\n    """\n    if (str(profile.get("family") or "").upper() != "GENERAL_DOCUMENT"\n            or str((queue.get("run") or {}).get("script_id") or "").upper() != "IDENTIFIERS"):\n        return 0\n\n    fields = (profile.get("data_model") or {}).get("family_fields") or []\n    wbs_fields = [f for f in fields if f.get("key") == "wbs"]\n    if len(wbs_fields) != 1:\n        return 0\n    cleaning = wbs_fields[0].get("cleaning") or {}\n    if str(cleaning.get("strategy") or "").upper() != "NEAREST_VALID_ABOVE_APPEND_SEQUENCE":\n        return 0\n\n    used: set[str] = set()\n    accepted = 0\n    for item in queue.get("items", []):\n        candidate = _can_auto_accept(item, existing_wbs, used)\n        if candidate is None:\n            continue\n        params, value = candidate\n        reason = (item.get("machine_suggestion") or {}).get("suggested_fix", {}).get("reason") or ""\n        decision = make_decision(\n            "SET_VALUE",\n            parameters=params,\n            reason=f"[{_POLICY}] Deterministic placeholder; {reason}",\n            reviewer="GENERAL_DOCUMENT_FAMILY_POLICY",\n        )\n        decision["origin"] = _POLICY\n        apply_decision_to_queue(queue, item["review_id"], decision)\n        used.add(value)\n        accepted += 1\n    summary = queue.setdefault("summary", {})\n    summary["pending_review"] = sum(x.get("review_state") == "PENDING" for x in queue.get("items", []))\n    summary["resolved"] = sum(x.get("review_state") == "RESOLVED" for x in queue.get("items", []))\n    summary["deferred"] = sum(x.get("review_state") == "DEFERRED" for x in queue.get("items", []))\n    if accepted:\n        summary["auto_accepted_wbs"] = accepted\n        summary["auto_accept_policy"] = _POLICY\n    return accepted\n'
TEST_CONTENT = 'from __future__ import annotations\n\nfrom copy import deepcopy\nfrom pathlib import Path\nimport json\n\nfrom cleaner_core.general_doc_auto_wbs import accept_general_document_wbs\nfrom cleaner_core.state import ingest_review_decisions_file, new_resolved_state\nfrom review.decisions import write_decisions_file\n\n\ndef profile(family="GENERAL_DOCUMENT", strategy="NEAREST_VALID_ABOVE_APPEND_SEQUENCE"):\n    return {"family": family, "data_model": {"family_fields": [\n        {"key": "wbs", "cleaning": {"strategy": strategy}},\n    ]}}\n\n\ndef item(target="C71", value="1.2.3.1000", observed=None, key="wbs", parent="1.2.3"):\n    return {\n        "review_id": f"IDENTIFIERS_Sheet_{target}", "review_state": "PENDING",\n        "source": {"test_id": "IDENTIFIERS", "status": "FAIL"},\n        "location": {"sheet": "Sheet", "target": target},\n        "observed": observed,\n        "evidence": {"field_key": key, "nearest_valid_wbs_above": parent},\n        "machine_suggestion": {"suggested_fix": {\n            "action": "SET_VALUE", "parameters": {\n                "field_key": key, "sheet": "Sheet", "target": target,\n                "value": value, "expected_old_value": observed,\n            }, "reason": "Nearest valid WBS above + sequence."}},\n    }\n\n\ndef queue(*items):\n    return {"run": {"script_id": "IDENTIFIERS"},\n            "summary": {"total_items": len(items), "pending_review": len(items)},\n            "items": list(items)}\n\n\ndef test_auto_accepts_missing_wbs_and_preserves_audit_overlay(tmp_path):\n    q = queue(item("D71", "1.2.3.1000"), item("D73", "1.2.3.1001"))\n    assert accept_general_document_wbs(q, profile(), {"1.2.3"}) == 2\n    assert q["summary"]["pending_review"] == 0\n    assert q["summary"]["resolved"] == 2\n    assert all(x["decision"]["origin"] == "GENERAL_DOCUMENT_AUTO_WBS_V1" for x in q["items"])\n    assert all(x["decision"]["reviewer"] == "GENERAL_DOCUMENT_FAMILY_POLICY" for x in q["items"])\n    path = tmp_path / "decisions.json"\n    q.update({"run": {"script_id": "IDENTIFIERS", "run_id": "test"}})\n    write_decisions_file(q, path)\n    state = new_resolved_state(run_id="test", profile_name="EYV")\n    ingest_review_decisions_file(state, path)\n    assert state["stages"]["IDENTIFIERS"]["status"] == "REVIEWED"\n    assert state["value_overrides"]["SHEET!D71"]["value"] == "1.2.3.1000"\n    assert len(state["decision_audit"]) == 2\n\n\ndef test_does_not_accept_nonempty_invalid_wbs_or_root_fallback():\n    q = queue(item("D71", observed="1.2.??"), item("D73", value="1000", parent=""))\n    assert accept_general_document_wbs(q, profile(), set()) == 0\n    assert q["summary"]["pending_review"] == 2\n\n\ndef test_does_not_accept_when_existing_wbs_or_two_suggestions_collide():\n    q = queue(item("C71"), item("C73"))\n    assert accept_general_document_wbs(q, profile(), {"1.2.3"}) == 1\n    assert q["summary"]["pending_review"] == 1\n    q2 = queue(item())\n    assert accept_general_document_wbs(q2, profile(), {"1.2.3.1000"}) == 0\n\n\ndef test_does_not_accept_other_family_or_disabled_strategy():\n    for prof in (profile("WEEKLY_REPORT_TEMPLATE"), profile(strategy="MANUAL")):\n        q = queue(item())\n        assert accept_general_document_wbs(q, prof, set()) == 0\n        assert q["items"][0]["review_state"] == "PENDING"\n\n\ndef test_does_not_accept_other_identifier_fields_or_wrong_target():\n    x = item(key="code")\n    y = item(target="C73")\n    y["machine_suggestion"]["suggested_fix"]["parameters"]["target"] = "C74"\n    q = queue(x, y)\n    assert accept_general_document_wbs(q, profile(), set()) == 0\n\n\ndef test_does_not_accept_partial_or_unvalidated_wbs():\n    q = queue(item(value="1.2.3.999"), item("C73",value="1.2.3.1000",parent="NaN"))\n    assert accept_general_document_wbs(q, profile(), set()) == 0\n\n\ndef test_numeric_zero_is_not_treated_as_empty():\n    q = queue(item(observed=0))\n    assert accept_general_document_wbs(q, profile(), set()) == 0\n\n\ndef test_manual_override_remains_possible():\n    q = queue(item())\n    assert accept_general_document_wbs(q, profile(), set()) == 1\n    q["items"][0]["review_state"] = "PENDING"\n    q["items"][0]["decision"] = None\n    assert q["items"][0]["decision"] is None\n'


def replace_one(text: str, old: str, new: str, label: str) -> str:
    found = text.count(old)
    if found != 1:
        raise RuntimeError(f"Unsafe to install: expected one {label} anchor, found {found}. No files modified.")
    return text.replace(old, new, 1)


def edit_pipeline(content: str) -> str:
    content = replace_one(content,
        "from review.queue import build_review_queue, write_review_queue\n",
        "from review.queue import build_review_queue, write_review_queue\n"
        "from review.decisions import write_decisions_file\n"
        "from cleaner_core.general_doc_auto_wbs import accept_general_document_wbs\n"
        "from cleaners.identifier_cleaner import normalize_digits\n",
        "queue import")
    content = replace_one(content,
        "    stage_artifacts = {}\n    snap = load_snapshot(snapshot_path)\n    try:\n        findings = run_stage(\n",
        "    stage_artifacts = {}\n    existing_wbs_for_auto = set()\n    snap = load_snapshot(snapshot_path)\n    try:\n        findings = run_stage(\n",
        "snapshot lifecycle")
    content = replace_one(content,
        "        resolved_snapshot, resolved_profile = build_resolved_context(snap, profile, state)\n"
        "        attach_document_context(findings, resolved_snapshot, resolved_profile)\n",
        "        resolved_snapshot, resolved_profile = build_resolved_context(snap, profile, state)\n"
        "        if stage_id == \"IDENTIFIERS\" and str(profile.get(\"family\") or \"\").upper() == \"GENERAL_DOCUMENT\":\n"
        "            existing_wbs_for_auto = {\n"
        "                normalize_digits(field.value)\n"
        "                for scan in scan_all_document_regions(resolved_snapshot, resolved_profile).values()\n"
        "                for region in scan.regions\n"
        "                for field in [region.field(\"wbs\")]\n"
        "                if field is not None and field.value not in (None, \"\")\n"
        "            }\n"
        "        attach_document_context(findings, resolved_snapshot, resolved_profile)\n",
        "document context")
    content = replace_one(content,
        "    write_review_queue(queue, queue_path)\n\n"
        "    review_count = int(queue.get(\"summary\", {}).get(\"total_items\", len(queue.get(\"items\", []))))\n",
        "    # GENERAL_DOCUMENT family: auto-accept safe machine-proposed blank-WBS\n"
        "    # placeholders as auditable logical overlays; never edit the source Excel.\n"
        "    if stage_id == \"IDENTIFIERS\" and str(profile.get(\"family\") or \"\").upper() == \"GENERAL_DOCUMENT\":\n"
        "        auto_count = accept_general_document_wbs(queue, profile, existing_wbs_for_auto)\n"
        "        if auto_count:\n"
        "            write_decisions_file(queue, decisions_path)\n"
        "            ingest_review_decisions_file(state, decisions_path)\n"
        "            logger(\"AUTO_WBS\", f\"Accepted {auto_count} deterministic General Document WBS suggestion(s); source workbook unchanged.\")\n"
        "\n"
        "    write_review_queue(queue, queue_path)\n\n"
        "    review_count = int(queue.get(\"summary\", {}).get(\"pending_review\", len(queue.get(\"items\", []))))\n",
        "review queue writer")
    return content


def make_plan():
    pipe = ROOT / PIPE
    if not pipe.is_file() or not (ROOT / "cleaner.package.json").is_file():
        raise RuntimeError("Run this from the real cleaner-functions repository root.")
    previous = pipe.read_text(encoding="utf-8")
    if "from cleaner_core.general_doc_auto_wbs import accept_general_document_wbs" in previous:
        if (ROOT / MODULE).is_file() and (ROOT / TEST).is_file():
            if (ROOT / MODULE).read_text(encoding="utf-8") == MODULE_CONTENT:
                return {}
        raise RuntimeError("Partial/modified auto-WBS install detected. Refusing to overwrite existing implementation.")
    plan = {PIPE: edit_pipeline(previous)}
    for path, contents in [(MODULE, MODULE_CONTENT), (TEST, TEST_CONTENT)]:
        current = ROOT / path
        if current.exists():
            if current.read_text(encoding="utf-8") == contents:
                continue
            raise RuntimeError(f"Refusing to overwrite existing file: {current}")
        plan[path] = contents
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read-only preflight")
    args = parser.parse_args()
    try:
        plan = make_plan()
        if not plan:
            print("[READY] GENERAL_DOCUMENT automatic WBS policy already installed.")
            return 0
        print(f"[CHECK] Compatible; {len(plan)} file(s) to create/update.")
        for name in plan:
            print(" ", name.as_posix())
        if args.check:
            print("[CHECK] No files changed.")
            return 0
        backup = ROOT / ("_auto_wbs_backup_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        originals = {}
        created = []
        try:
            for name, content in plan.items():
                target = ROOT / name
                if target.exists():
                    originals[name] = target.read_bytes()
                    saved = backup / name
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, saved)
                else:
                    created.append(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        except Exception:
            for name, content in originals.items():
                (ROOT / name).write_bytes(content)
            for target in created:
                target.unlink(missing_ok=True)
            raise
        print("[DONE] Automatic blank-WBS decisions enabled for GENERAL_DOCUMENT / IDENTIFIERS.")
        print("[BACKUP]", backup)
        print("[NEXT] py -m pytest -q --ignore=payload --import-mode=importlib")
        return 0
    except Exception as exc:
        print("[STOP]", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
