AZD 63KV transaction-rhythm recovery patch

Changes:
- fallback block-width inference from stable semantic anchor spacing (e.g. STATUS columns)
- value-level recovery of send/receive date-bearing offsets in vertically mixed transaction columns
- profile-driven thresholds for modular project reuse
- SLOT_SCHEMA logging now reports block_source and anchor evidence
- regression tests for status-anchor spacing and mixed date/reference offsets

Apply by extracting this archive over the cleaner-functions project root.

Then run:
  python -m pytest -q unit_tests

Expected:
  54 passed

Then rerun AZD SLOT_SCHEMA and FIELD_VALIDATION using the existing run-id.
