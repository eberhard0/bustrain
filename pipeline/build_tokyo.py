#!/usr/bin/env python3
"""Build the Tokyo city dataset.

Feeds:
  toeitrain  — Toei subway, REAL GTFS (ODPT public files, no key)
  toeibus    — Toei bus, REAL GTFS (ODPT public files, no key)
  tokyometro — Tokyo Metro + JR Yamanote, headway model (build_tokyo_rail.py)

English names come from the Toei feeds' translations.txt (standard GTFS
translations: table_name/field_name/field_value/language) plus OSM name:en
for the generated stations. Full Metro/JR timetables need an ODPT developer
key — roadmap.
Output: web/data/tokyo/
"""
import csv
import json
from datetime import date
from pathlib import Path

from gtfs_core import build_city

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "tokyo"
RAW = ROOT / "data" / "raw"

FEEDS = {
    "toeitrain": {"name": "都営地下鉄", "name_en": "Toei Subway",
                  "color": "#127A32", "prefix": "tt", "kind": "train"},
    "tokyometro": {"name": "東京メトロ・山手線", "name_en": "Tokyo Metro & Yamanote (headway model)",
                   "color": "#109ED4", "prefix": "tm", "kind": "train"},
    "toeibus": {"name": "都営バス", "name_en": "Toei Bus",
                "color": "#0F9D58", "prefix": "tk", "kind": "bus"},
}


def translations_en(feed):
    """GTFS translations.txt (table/field/value/language) -> {jp: en}."""
    p = RAW / feed / "translations.txt"
    out = {}
    if not p.exists():
        return out
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("language") == "en" and r.get("field_name") == "stop_name"
                    and r.get("field_value") and r.get("translation")):
                out[r["field_value"].strip()] = r["translation"].strip()
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stops, feed_meta, _ = build_city(FEEDS, RAW, OUT)
    index = {"generated": date.today().isoformat(), "feeds": feed_meta, "stops": stops}
    (OUT / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (OUT / "corridors.json").write_text('{"pairs":{},"stations":{}}', encoding="utf-8")

    names = {}
    names.update(translations_en("toeitrain"))
    names.update(translations_en("toeibus"))
    extra = RAW / "tokyometro" / "names_en_extra.json"
    if extra.exists():
        names.update(json.loads(extra.read_text(encoding="utf-8")))
    lines_en = {"浅草線": "Asakusa Line", "三田線": "Mita Line",
                "新宿線": "Shinjuku Line", "大江戸線": "Ōedo Line"}
    for jp, en in lines_en.items():
        names.setdefault(jp, en)
    (OUT / "names_en.json").write_text(
        json.dumps({"names": names, "lines": lines_en, "trains": {}},
                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"tokyo: {len(stops)} stops, {len(names)} EN names -> {OUT}")


if __name__ == "__main__":
    main()
