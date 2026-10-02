# Card Map

`CARD_MAP` is the explicit bridge between document boundaries and content validation.

It answers two concrete questions for every `DocumentRegion`:

1. What part of the card contains identifiers? (`A:C` for AZD today.)
2. What part contains operational data? (`D:<right edge>` derived from the workbook.)

For each card it stores:

- `identifier_range`
- `data_range`
- visible merged/unmerged populated `slots`
- row-relative slot geometry
- current slot values for inspection

It intentionally does **not** validate dates, references, or status yet. Those validators should be added only after semantic field roles are mapped explicitly in the profile.

Current semantic targets are:

- `reference`
- `send_date`
- `receive_date`
- `status`

The old `DOCUMENT_STRUCTURE` fingerprinting code may remain available as a diagnostic, but it is no longer a required pipeline review stage.

## Visual inspection

`CARD_MAP` is not a review queue of abstract patterns. To verify that the derived
boundaries are meaningful, use:

```powershell
python .\dev\inspect_card_map.py ".\runs\<run-id>\card_maps.json"
```

The inspector activates the already-open Excel workbook, selects the current
card's **data range**, and prints its identifier range, data range, slot count,
and a short value preview. Use `n`/`p` to walk cards and `s` to jump to the next
sheet.
