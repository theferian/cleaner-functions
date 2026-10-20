from pathlib import Path
import datetime
import json
import shutil
import sys

ROOT = Path.cwd()

STATUS_JSON = ROOT / "configs" / "status_library.json"
THREE_LISTS = ROOT / "functions" / "engineering_control" / "three_lists.py"
TESTS = ROOT / "unit_tests" / "test_engineering_three_lists.py"
TASKS = ROOT / "docs" / "DEMO_TASK_LIST.md"

for path in (STATUS_JSON, THREE_LISTS, TESTS):
    if not path.exists():
        raise SystemExit(f"[STOP] Missing required file: {path}")


def load_text(path):
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    return text, newline


def save_text(path, text, newline):
    if newline == "\r\n":
        text = text.replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


# ------------------------------------------------------------
# Prepare everything in memory first.
# Nothing is written until all anchors have been validated.
# ------------------------------------------------------------

# 1. STATUS LIBRARY
status_data = json.loads(STATUS_JSON.read_text(encoding="utf-8-sig"))

statuses = status_data.setdefault("statuses", {})

statuses.update({
    "A": {
        "code": "A",
        "aliases": [],
        "meaning": "Approved",
        "meaning_fa": "تایید شده",
        "responsibility_after_receive": None,
        "action_required": False,
        "notes": (
            "User-confirmed: engineering work is closed; "
            "candidate for WBS finish approval."
        ),
        "source": "user-confirmed-2026-10-15"
    },
    "AP": {
        "code": "AP",
        "aliases": [],
        "meaning": "Approved",
        "meaning_fa": "تایید شده",
        "responsibility_after_receive": None,
        "action_required": False,
        "notes": (
            "User-confirmed: engineering work is closed; "
            "candidate for WBS finish approval."
        ),
        "source": "user-confirmed-2026-10-15"
    },
    "AN": {
        "code": "AN",
        "aliases": ["A.N"],
        "meaning": "Approved as Noted",
        "meaning_fa": "تایید با اعمال نکات",
        "responsibility_after_receive": "COMPANY",
        "action_required": True,
        "notes": (
            "User-confirmed: further engineering action is required; "
            "do not close engineering."
        ),
        "source": "user-confirmed-2026-10-15"
    },
    "CM": {
        "code": "CM",
        "aliases": ["C.M"],
        "meaning": "Commented",
        "meaning_fa": "دارای کامنت",
        "responsibility_after_receive": "COMPANY",
        "action_required": True,
        "notes": (
            "User-confirmed: comments require company engineering action."
        ),
        "source": "user-confirmed-2026-10-15"
    },
    "FC": {
        "code": "FC",
        "aliases": ["F.C"],
        "meaning": "For Construction",
        "meaning_fa": "جهت اجرا",
        "responsibility_after_receive": None,
        "action_required": False,
        "notes": (
            "User-confirmed: engineering work is closed; "
            "candidate for WBS finish approval."
        ),
        "source": "user-confirmed-2026-10-15"
    },
    "RJ": {
        "code": "RJ",
        "aliases": [],
        "meaning": "Rejected",
        "meaning_fa": "رد شده",
        "responsibility_after_receive": "COMPANY",
        "action_required": True,
        "notes": (
            "User-confirmed: rejected; company engineering revision/action "
            "is required."
        ),
        "source": "user-confirmed-2026-10-15"
    }
})

status_newline = "\r\n" if b"\r\n" in STATUS_JSON.read_bytes() else "\n"
status_text = json.dumps(status_data, ensure_ascii=False, indent=2) + "\n"


# 2. THREE-LIST LOGIC
three_text, three_nl = load_text(THREE_LISTS)

# Strict NOT_SENT:
# no canonical interactions at all, rather than merely no SEND.
if 'calculation_status="NO_INTERACTION_HISTORY"' not in three_text:
    if three_text.count("        if not sends:\n") != 1:
        raise SystemExit(
            "[STOP] Expected exactly one 'if not sends:' anchor. "
            "Nothing has been written."
        )

    if three_text.count('calculation_status="NO_SEND_EVENT"') != 1:
        raise SystemExit(
            "[STOP] Expected exactly one NO_SEND_EVENT anchor. "
            "Nothing has been written."
        )

    three_text = three_text.replace(
        "        if not sends:\n",
        "        if not ordered:\n",
        1,
    )

    three_text = three_text.replace(
        'calculation_status="NO_SEND_EVENT"',
        'calculation_status="NO_INTERACTION_HISTORY"',
        1,
    )


# Closed statuses must leave all three active lists.
closed_marker = "Closed engineering statuses A/AP/FC"

if closed_marker not in three_text:
    anchor = (
        '        if latest.send_or_receive == "receive" '
        'and status not in response_statuses:\n'
    )

    if three_text.count(anchor) != 1:
        raise SystemExit(
            "[STOP] Could not safely find receive-status classifier anchor. "
            "Nothing has been written."
        )

    closed_logic = (
        "        # Closed engineering statuses A/AP/FC require no further\n"
        "        # engineering work and are excluded from all three active\n"
        "        # engineering lists. WBS finish approval is evaluated later.\n"
        "        if (\n"
        '            latest.send_or_receive == "receive"\n'
        "            and status_definition is not None\n"
        "            and status_definition.action_required is False\n"
        "        ):\n"
        "            continue\n\n"
    )

    three_text = three_text.replace(
        anchor,
        closed_logic + anchor,
        1,
    )


# Prefer the reusable status library as the response-status authority.
old_response_rule = (
    'response_statuses = {"CM", "RJ"} '
    '| status_library.statuses_for_responsibility("COMPANY")'
)

if old_response_rule in three_text:
    three_text = three_text.replace(
        old_response_rule,
        'response_statuses = '
        'status_library.statuses_for_responsibility("COMPANY")',
        1,
    )


# 3. REGRESSION TESTS
test_text, test_nl = load_text(TESTS)

if (
    'assert result.not_sent[0].calculation_status == "NO_SEND_EVENT"'
    in test_text
):
    test_text = test_text.replace(
        'assert result.not_sent[0].calculation_status == "NO_SEND_EVENT"',
        'assert result.not_sent[0].calculation_status == '
        '"NO_INTERACTION_HISTORY"',
        1,
    )


extra_tests = r'''

def test_not_sent_requires_fully_empty_interaction_history():
    records = [
        rec(
            side="receive",
            rev="Z",
            date="1404/10/03",
            status="A",
            block=0,
            name="GEOTECHNICAL",
        ),
    ]

    result = build_three_engineering_lists(
        records,
        status_date="1405/01/01",
        document_inventory=[inventory(1, "GEOTECHNICAL")],
    )

    assert not result.not_sent
    assert not result.company_delay
    assert not result.consultant_delay


def test_closed_statuses_leave_all_active_engineering_lists():
    for status in ("A", "AP", "FC", "F.C"):
        records = [
            rec(
                side="send",
                rev="A",
                date="1405/01/01",
                block=0,
            ),
            rec(
                side="receive",
                rev="A",
                date="1405/01/05",
                status=status,
                block=0,
            ),
        ]

        result = build_three_engineering_lists(
            records,
            status_date="1405/01/15",
            document_inventory=[inventory(1)],
        )

        assert not result.not_sent, status
        assert not result.company_delay, status
        assert not result.consultant_delay, status
        assert not result.diagnostics, status


def test_action_required_statuses_remain_company_candidates():
    for status in ("AN", "A.N", "CM", "C.M", "RJ"):
        records = [
            rec(
                side="send",
                rev="A",
                date="1405/01/01",
                block=0,
            ),
            rec(
                side="receive",
                rev="A",
                date="1405/01/05",
                status=status,
                block=0,
            ),
        ]

        result = build_three_engineering_lists(
            records,
            status_date="1405/01/15",
            document_inventory=[inventory(1)],
        )

        assert len(result.company_delay) == 1, status
        assert not result.consultant_delay, status
        assert not result.not_sent, status


def test_latest_closed_revision_overrides_older_open_revision():
    records = [
        rec(
            side="send",
            rev="Z",
            date="1405/01/01",
            block=0,
        ),
        rec(
            side="receive",
            rev="Z",
            date="1405/01/05",
            status="CM",
            block=0,
        ),
        rec(
            side="send",
            rev="A",
            date="1405/01/10",
            block=1,
        ),
        rec(
            side="receive",
            rev="A",
            date="1405/01/12",
            status="A",
            block=1,
        ),
    ]

    result = build_three_engineering_lists(
        records,
        status_date="1405/01/20",
        document_inventory=[inventory(1)],
    )

    assert not result.not_sent
    assert not result.company_delay
    assert not result.consultant_delay
    assert not result.diagnostics
'''

if "def test_not_sent_requires_fully_empty_interaction_history(" not in test_text:
    test_text = test_text.rstrip() + extra_tests + "\n"


# 4. TASK LIST
task_text = """# Weekly Report Demonstration — Working Task List

## AZD critical path

- [x] General Document Cleaner stages
- [x] Board→Log
- [x] Coverage Audit
- [x] Weekly Report initial structure discovery
- [x] 4A.1–4A.6 Define engineering status semantics
- [x] 4A.7 Patch status semantics + strict NOT_SENT
- [ ] 4A.8 Rerun AZD engineering lists and compare mismatches
- [ ] 4A.9 Generate/confirm WBS finish-candidate signals
- [ ] Report-date authority
- [ ] WBS row classification
- [ ] Progress write policy
- [ ] Formula/manual/protected map
- [ ] Engineering-list insertion/resizing rules
- [ ] Resolve workbook anomalies
- [ ] Publishing validation rules
- [ ] Freeze AZD WEEKLY_REPORT_TEMPLATE profile
- [ ] Dry run current-week AZD report
- [ ] Publish verified AZD weekly report

## General Document production route

After the family-level engineering rules are stable, repeat the
approved General Document process for the remaining projects.

NGN = explicitly NO_DOCUMENTS when confirmed; do not fabricate a run.
"""


# ------------------------------------------------------------
# All validation succeeded. Make backups, then write.
# ------------------------------------------------------------

stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
backup = ROOT / ".engineering_status_backup" / stamp

for path in (STATUS_JSON, THREE_LISTS, TESTS):
    target = backup / path.relative_to(ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)


STATUS_JSON.write_text(status_text, encoding="utf-8")

save_text(
    THREE_LISTS,
    three_text,
    three_nl,
)

save_text(
    TESTS,
    test_text,
    test_nl,
)

TASKS.parent.mkdir(parents=True, exist_ok=True)

if not TASKS.exists():
    TASKS.write_text(task_text, encoding="utf-8")
else:
    existing = TASKS.read_text(encoding="utf-8")

    for line in (
        "- [x] 4A.7 Patch status semantics + strict NOT_SENT",
        "- [ ] 4A.8 Rerun AZD engineering lists and compare mismatches",
        "- [ ] 4A.9 Generate/confirm WBS finish-candidate signals",
    ):
        if line not in existing:
            existing += "\n" + line

    TASKS.write_text(existing, encoding="utf-8")


print("[OK] Task 4A.7 live patch applied")
print(f"[BACKUP] {backup}")

print("\nBusiness rule:")
print("  CLOSED : A, AP, FC/F.C")
print("  ACTIVE : AN/A.N, CM/C.M, RJ")
print("  UNKNOWN: N.A")
print("  NOT_SENT = zero interaction history")

print("\nNext:")
print("  python -m pytest -q unit_tests")