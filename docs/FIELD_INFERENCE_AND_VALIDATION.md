# Slot schema inference and field validation

The transaction-data workflow is intentionally layered:

1. `CARD_MAP` finds every document card and its data area.
2. `SLOT_SCHEMA` studies worksheet headers and cross-card value patterns to infer repeating transaction blocks and field roles.
3. `FIELD_VALIDATION` validates only fields whose role was inferred with enough evidence.

## Jalali dates

Dates are normalized to Persian/Arabic digits -> ASCII digits, common separators -> `/`, and zero-padded `YYYY/MM/DD`. Validation then checks the actual Jalali month/day limits, including Esfand leap-year rules. A value that is already canonical and valid is silent. A value that becomes valid after deterministic normalization is sent to review with a `SET_VALUE` suggestion. An invalid/ambiguous date is sent to review without inventing a replacement.

## References

Reference validation is activated only when a `reference` role is found and enough populated values exist. The system groups values by structural character shape, chooses the majority shape, and emits a candidate regex plus coverage. If coverage is below the configured threshold, no automatic reference rule is used. Values matching the inferred rule are silent. Outliers enter review. Safe formatting normalization is suggested only when the normalized form actually matches the inferred regex.

## Status

Status columns are inferred from headers or repeating short-code patterns. A vocabulary is learned from recurring normalized codes. Common valid values are silent; outliers and non-canonical variants enter review.

## Conservative principle

Inference does not turn arbitrary text into a semantic field. When role/block confidence is insufficient, `SLOT_SCHEMA` reports a schema-review item instead of running a noisy validator.

## Per-column semantic confidence

`SLOT_SCHEMA` now classifies every absolute data column before assigning a validation role. The semantic types are `DATE`, `STATUS`, `REFERENCE`, `TEXT`, `NUMBER`, `CODE`, `MIXED`, or `UNKNOWN`.

A repeating block pattern may describe the overall transaction rhythm, but it cannot force a semantic role onto an individual column. A column receives a validator only when its own observed values reach the configured semantic-confidence threshold and the inferred block/header role is compatible with that semantic type.

For example, if `E` is overwhelmingly Jalali dates but `H` alternates between dates and business text, `E` may become `receive_date` while `H` remains `MIXED`. `FIELD_VALIDATION` ignores `H` entirely until a clearer rule is established.

## Fundamental block width

Mixed/unknown columns are excluded from block-period scoring. This lets stable anchors such as date/status positions determine the repeating rhythm and prevents a three-column transaction pattern from being mistaken for a six-column harmonic merely because one slot is mixed.

## Card-relative vertical lanes

AZD transaction cards are two-dimensional. A single absolute Excel column can hold different semantic fields at different vertical positions inside the same document card. For example, a two-row card may contain a date in `D(top)` and a reference or narrative in `D(bottom)`. A four-row card may represent the same logic with merged rows 1–2 as the top lane and rows 3–4 as the bottom lane.

The inference layer therefore normalizes each mapped slot into `TOP`, `BOTTOM`, `FULL`, or (rarely) `MIDDLE` relative to its `DocumentRegion`. Semantic classification and validation roles are assigned to `(column, lane)`, not to the absolute column alone. This prevents valid reference/narrative cells from being sent through the Jalali date validator merely because they share a column with dates.

## Physical sub-slot dispatch inside multi-row cards

`TOP/BOTTOM` is only a statistical schema summary; it is not allowed to force the role of every physical cell. Multi-row AZD cards can stack several events in one transaction column, for example `date -> reference -> date -> reference`. During validation, each actual mapped sub-slot is therefore dispatched by both its horizontal transaction offset and its observed value shape:

- Jalali-looking values are validated as dates.
- Compact document-number shapes such as `1404/ES/S/1601` are validated as references.
- Narrative Persian text is treated as an explanation/meeting-note field rather than as a reference or date.
- Stable status offsets remain status fields so new/invalid status codes can still be detected.

This prevents a valid later-row date from being checked against the reference regex, and prevents a valid letter number from being checked as a Jalali date.

## Explanations and embedded Jalali dates

Explanation/meeting-note text is preserved as text. If it contains an embedded short Jalali date, the cleaner normalizes only that date token and proposes a `SET_VALUE` review action for the full preserved sentence. For example, `عطف به بند شماره 1 صورتجلسه مورخ 04/06/03` becomes `عطف به بند شماره 1 صورتجلسه مورخ 1404/06/03`. Invalid embedded calendar dates are never invented or silently corrected; they remain review items without an automatic replacement.


## Global Jalali date safety audit

Semantic inference is no longer the only way a date is checked. `FIELD_VALIDATION` also performs a safety-net scan across **every populated mapped card sub-slot**, including slots classified as `REFERENCE`, `TEXT`, `MIXED`, or still unresolved. This preserves the useful behavior of the earlier COM checker, which searched cells directly, while adding actual Jalali calendar validation.

Four-digit Jalali-looking tokens beginning with `13xx` or `14xx` are audited wherever they occur. Two-digit years are audited only when explicit date context exists (for example `مورخ`, `تاریخ`, or `date`) to avoid treating numeric document-reference fragments as dates. Valid canonical tokens are silent. Valid but non-canonical tokens produce a deterministic normalization suggestion. Calendar-invalid tokens enter review without an invented replacement.

This safety net is especially important for sheets whose transaction schema is not yet fully resolved: malformed dates can still be found even when `SLOT_SCHEMA` has not assigned a date role to the containing column/sub-slot.

## Receive-date / status relationship

For sheets with a resolved repeating transaction block, a valid `receive_date` event must have a non-empty `status` in the same transaction block and overlapping vertical event span. This rule is derived from the earlier `data_check.py` receive/status checker, but uses the cleaner's card and merge geometry rather than raw row scanning. Missing status is a review finding; an unfamiliar but non-empty status is handled separately by the status-vocabulary validator.

## Global date audit v2

The date safety net scans every mapped card sub-slot even when the slot already has a semantic role. This makes the audit an independent cross-check rather than only a fallback for unmapped fields. Duplicate findings are suppressed when the semantic date/explanation validator already reported the same physical slot.

Candidate discovery is intentionally broader than validity: malformed numeric triples such as `1404/013/01`, `1404/07/031`, or a three-digit-year typo are still discovered and then rejected by Jalali calendar validation. Two-digit years remain restricted to explicit date context (for example `مورخ 04/06/03`) to avoid treating arbitrary codes as dates.

A separate review-only chronology rule checks paired send/receive events. When both dates are valid but the receive date precedes the send date, the issue is reported as `DATE_CHRONOLOGY`; no automatic correction is generated.

## Semantic-anchor fallback for mixed transaction boards

Some project sheets have a clear repeating transaction rhythm even when the correspondence columns are vertically mixed. In AZD `63KV SS`, for example, stable status columns recur at `F, I, L, O, R` while the intervening columns may stack dates, references and narrative notes.

The schema inference therefore uses two levels of evidence:

1. **Whole-column semantic periodicity** remains the primary block-width detector.
2. **Semantic-anchor spacing** is a fallback when the primary score is below threshold. Repeated high-confidence anchors (preferably `STATUS`) can establish the horizontal block width from their spacing.

Once a block width is resolved, mixed correspondence offsets are inspected at the **value level**. Repeated date values can establish the first date-bearing offset as `send_date` and the second as `receive_date`, while reference-shaped values remain references and narrative values remain explanations. This keeps the model compatible with stacked multi-event cards without requiring one absolute lane to be semantically pure.

The thresholds are profile-driven under `data_model.field_inference`:

- `anchor_block_inference`
- `anchor_min_columns`
- `anchor_min_spacing_coverage`
- `mixed_offset_date_min_samples`
- `mixed_offset_date_min_share`

This fallback is intended to be reusable across project profiles; project-specific coordinates are evidence, not hard-coded engine logic.

## Semantic value overrides for irregular cards

The reader is intentionally allowed to prefer high-confidence value semantics over
expected geometry. If a value is already part of the inferred status vocabulary
(e.g. `A.N`, `CM`, `RJ`) but an irregular card places it in a position normally
used for receive/reference data, the value is read as `status`. This is a reader
rule, not a workbook-cleaning rule: no document mutation is requested merely to
make the card conform to the majority layout.

This behaviour is controlled by
`data_model.field_inference.known_status_overrides_geometry` (default `true`).
