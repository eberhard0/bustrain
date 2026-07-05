#!/usr/bin/env python3
"""Build the Jakarta city dataset (TransJakarta GTFS + OSM landmarks).

Jakarta edition v1: buses only (no open rail GTFS yet), IDR fares, no
romaji layer (Indonesian is Latin-script).
Input: data/raw/transjakarta/*.txt  (https://gtfs.transjakarta.co.id)
Output: web/data/jakarta/
"""
import json
from datetime import date
from pathlib import Path

from gtfs_core import build_city

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "jakarta"

FEEDS = {
    "transjakarta": {"name": "Transjakarta", "name_en": "Transjakarta",
                     "color": "#00549F", "prefix": "tj"},
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stops, feed_meta, _ = build_city(FEEDS, ROOT / "data" / "raw", OUT)
    index = {"generated": date.today().isoformat(), "feeds": feed_meta, "stops": stops}
    (OUT / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # no rail data yet; Latin script needs no transliteration layer
    (OUT / "corridors.json").write_text('{"pairs":{},"stations":{}}', encoding="utf-8")
    (OUT / "names_en.json").write_text('{"names":{},"lines":{},"trains":{}}', encoding="utf-8")
    print(f"jakarta: {len(stops)} stops -> {OUT}")


if __name__ == "__main__":
    main()
