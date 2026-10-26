# General Document V07.1 — same-day review and absolute hyperlinks

Extract into the cleaner-functions repository root, replacing the included V07
files. Existing profiles, saved decisions, runs and source workbooks stay intact.

Install the retrieval hook once (with an automatic backup):

```bat
py INSTALL_GENERAL_DOCUMENT_V071.py --check
py INSTALL_GENERAL_DOCUMENT_V071.py --apply
py unit_tests\test_general_document_v07.py
py unit_tests\test_general_doc_links_v071.py
```

## Same-day events

SAME_DAY_DIRECTION_ORDER_UNVERIFIED is no longer an engineering-review error.
The dates and calculated rows remain intact. Other diagnostics remain visible.
The review list updates when engineering lists are recalculated; previously
written CSV/JSON files are not silently edited on installation. V07-generated
chronology conflicts now carry the document name and WBS when available.

To exit the current reviewer, use b at the individual decision prompt, then p
at its main review prompt. Resume using the same project, actual run ID and
report date:

```bat
py RUN_GENERAL_DOCUMENT_V07.py --project AZD --run-id azd_20261022T195101 --status-date 1405/07/29
```

Use that example only if it is the run currently being reviewed. No --new-run
is needed for this update. The report date remains your required command input.

## Retrieval hyperlinks

Your existing command now converts links in the retrieved General Doc copy:

```bat
py pipeline\weekly_report_pipeline.py prepare-general-doc --project AZD --overwrite
```

Relative external hyperlinks and literal HYPERLINK("relative path",...) formulas
are resolved against the ORIGINAL source workbook directory, honoring Excel's
Hyperlink Base property. Absolute links and internal sheet links remain unchanged.
Conversions use absolute file URIs, e.g. file:///W:/... or file://server/share/....
Mapped-drive links still require that drive mapping on the machine opening them;
V07.1 does not guess a UNC mapping for W: or Y:.

The source workbook is not changed. The retrieval manifest records separate
source and converted-copy hashes; its primary sha256 refers to the actual
retrieved bytes. A .xlsx.links.json sidecar records every converted target.
Link conversion uses OOXML package edits, preserving unrelated XML/formatting,
drawings, and binary content. It does not open linked files or test permissions.

Dynamic formulas, such as HYPERLINK(A2&"/file.pdf",...), are preserved and listed
as unresolved in the link receipt. They cannot be reliably rewritten as literals
without changing their formula behavior. Current hook expects .xlsx/.xlsm ZIP
workbooks, matching the existing General Doc retrieval workflow.

For existing runs, the corrected working copy is rebuilt as necessary and links
are resolved using its matching retrieval manifest/source lineage when available.
A missing original location produces [LINKS REVIEW] and is recorded in
working_copy_execution.json; no source base is guessed.

If needed, repair an independent retrieved copy explicitly (not a run-bound file):

```bat
py FIX_GENERAL_DOC_LINKS.py --workbook "input\7_AZD_LATEST_GENERAL_DOC_14050730.xlsx" --source-path "W:\00-1403\1403-02-05-230kV Azad\Letter\technical\updated Doc\General - Azad.xlsx"
```

That command creates a backup. Do not run it on a file bound to an existing run;
resume V07 instead so its source hash stays intact. Likewise, avoid retrieval
--overwrite on an input workbook still bound to an older V06 run: finish/resume
that run first, or choose a different retrieval destination.

Validation: 19 Cleaner checks + 11 hyperlink/retrieval checks passed. These include
real retrieval-service calls on temporary workbook packages, source preservation,
hash lineage, Windows/UNC/Persian paths, Hyperlink Base, package preservation,
formula handling, and suppressing only the requested same-day diagnostic.
Windows Excel and your current network files still need the live test.
