from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dev.review_findings import ExcelReviewNavigator


def _cards(payload: dict) -> list[dict]:
    result: list[dict] = []
    for sheet, scan in (payload.get("sheets") or {}).items():
        for card in scan.get("cards") or []:
            item = dict(card)
            item["sheet"] = sheet
            result.append(item)
    return result


def _preview_slots(card: dict, limit: int = 8) -> str:
    slots = card.get("slots") or []
    parts = []
    for slot in slots[:limit]:
        value = slot.get("value")
        value_text = "" if value is None else str(value).replace("\n", " ")
        if len(value_text) > 28:
            value_text = value_text[:25] + "..."
        parts.append(f"{slot.get('address')}={value_text!r}")
    return "; ".join(parts) if parts else "(no populated/merged data slots)"


def main():
    parser = argparse.ArgumentParser(description="Visually inspect derived CARD_MAP regions in live Excel.")
    parser.add_argument("card_map_json")
    args = parser.parse_args()

    path = Path(args.card_map_json)
    payload = json.loads(path.read_text(encoding="utf-8"))
    cards = _cards(payload)
    if not cards:
        print("No cards found in the card-map artifact.")
        return

    queue_like = {"workbook": payload.get("workbook") or {}}
    navigator = ExcelReviewNavigator(queue_like, enabled=True)
    if not navigator.available:
        print(f"Excel navigation unavailable: {navigator.error}")
        return

    index = 0
    while True:
        card = cards[index]
        selection = card.get("data_range") or card.get("identifier_range")
        review_item = {
            "location": {"sheet": card["sheet"], "target": selection},
            "evidence": {},
        }
        try:
            shown = navigator.show(review_item, selection)
        except Exception as exc:
            shown = f"navigation error: {exc}"

        print("\n" + "=" * 88)
        print(f"CARD {index + 1}/{len(cards)}")
        print(f"Sheet       : {card['sheet']}")
        print(f"Rows        : {card.get('start_row')}:{card.get('end_row')}")
        print(f"Identifiers : {card.get('identifier_range')}")
        print(f"Data        : {card.get('data_range')}")
        print(f"Excel       : {shown}")
        print(f"Slots       : {len(card.get('slots') or [])}")
        print(f"Preview     : {_preview_slots(card)}")
        print("Commands    : n next | p previous | s next sheet | q quit")

        cmd = input("Inspect: ").strip().lower() or "n"
        if cmd == "q":
            break
        if cmd == "p":
            index = (index - 1) % len(cards)
            continue
        if cmd == "s":
            sheet = card["sheet"]
            next_index = next((i for i in range(index + 1, len(cards)) if cards[i]["sheet"] != sheet), None)
            index = 0 if next_index is None else next_index
            continue
        index = (index + 1) % len(cards)


if __name__ == "__main__":
    main()
