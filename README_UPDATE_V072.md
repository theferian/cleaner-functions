# General Document Cleaner V07.2 — chronology lanes and one WBS per document

Extract the ZIP into the Cleaner repository root and replace the included files. The V07.1 retrieval hook remains compatible; do not install a second hook.

## Chronology correction

General Document cards can contain vertically repeated SEND and RECEIVE entries in parallel lanes. A later SEND can be dated before an earlier RECEIVE when replies overlap. V07.2 checks each direction in its own board order, checks a SEND/RECEIVE pair when both occupy the same physical row, and retains the combined chronology check for cards with no aligned rows. This removes false conflicts such as the supplied Control Schematic sequence while preserving actual backwards dates within a lane or a receive date earlier than its same-row send.

Existing diagnostics and list outputs are not edited automatically. Recalculate engineering lists for the run to refresh the audit.

## One WBS per document

Every document must have exactly one non-empty WBS. A missing assignment is reported as `DOCUMENT_WBS_REQUIRED`; inconsistent WBS values for one document are reported as `DOCUMENT_WBS_CONFLICT`. That document is held out of the three responsibility lists until the identity is corrected, and remains visible in diagnostics. Reuse of one WBS across separate documents is not checked by this rule.

## Validate

```bat
py unit_tests\test_general_document_v07.py
py unit_tests\test_general_doc_links_v071.py
```

Validation: 22 Cleaner/chronology/WBS checks + 11 hyperlink/retrieval checks.
