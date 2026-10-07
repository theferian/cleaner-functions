STATUS LIBRARY PATCH
====================

Purpose
-------
Add a reusable semantic library for engineering-document status codes.

Confirmed initial definition:
RJ = Rejected / رد شده
After a received RJ, responsibility is on the COMPANY and action is required.

Important
---------
This patch intentionally contains NO project-specific JND/FSH exception or solution files.
It is safe to overlay on the current working tree without overwriting learned review state.

After applying
--------------
1) python -m pytest -q unit_tests
   Expected: 144 passed

2) Re-run JND FIELD_VALIDATION using the existing run-id:
   python ./pipeline/project_pipeline.py --project JND --run-id "jnd_20261007T022038" --stage FIELD_VALIDATION

RJ should no longer appear as a review finding. The total should drop from 6 to 5 if no other source state changed.

Status-library commands
-----------------------
python ./dev/status_library.py list
python ./dev/status_library.py show RJ

Add/update a status after its meaning is confirmed:
python ./dev/status_library.py add CODE --meaning "..." --meaning-fa "..." --responsibility COMPANY --action-required yes

Do not declare aliases such as C.M -> CM or F.C -> FC until their semantic equivalence is confirmed.
