#!/usr/bin/env python3
"""Build the Nagoya city dataset.

Feeds:
  nagoyabus    — Nagoya City Bus, REAL GTFS-JP (BODIK open data, 2026-03-28 dia)
  nagoyasubway — Municipal subway 6 lines, headway model (build_nagoya_rail.py;
                 the bureau publishes no rail GTFS)

English names: the bus feed's translations.txt (table format) `en` rows, kana
readings romanized as fallback, OSM name:en for subway stations.
Output: web/data/nagoya/
"""
import csv
import json
from datetime import date
from pathlib import Path

from build_names_en import kana_to_romaji
from gtfs_core import build_city

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "nagoya"
RAW = ROOT / "data" / "raw"

FEEDS = {
    "nagoyasubway": {"name": "名古屋市営地下鉄", "name_en": "Nagoya Subway (headway model)",
                     "color": "#F3C300", "prefix": "ns", "kind": "train"},
    "nagoyabus": {"name": "名古屋市バス", "name_en": "Nagoya City Bus",
                  "color": "#0F9D58", "prefix": "nb", "kind": "bus"},
}


def bus_names_en():
    """translations.txt (table format): en rows first, kana->romaji fallback."""
    p = RAW / "nagoyabus" / "translations.txt"
    en, kana = {}, {}
    if not p.exists():
        return {}
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            v, tr = (r.get("field_value") or "").strip(), (r.get("translation") or "").strip()
            if not v or not tr:
                continue
            if r.get("language") == "en":
                en[v] = tr
            elif r.get("language") == "ja-Hrkt":
                kana[v] = tr
    out = {v: kana_to_romaji(k) for v, k in kana.items() if v not in en}
    out.update(en)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stops, feed_meta, _ = build_city(FEEDS, RAW, OUT)
    index = {"generated": date.today().isoformat(), "feeds": feed_meta, "stops": stops}
    (OUT / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (OUT / "corridors.json").write_text('{"pairs":{},"stations":{}}', encoding="utf-8")

    names = bus_names_en()
    extra = RAW / "nagoyasubway" / "names_en_extra.json"
    if extra.exists():
        names.update(json.loads(extra.read_text(encoding="utf-8")))
    lines_en = {"東山線": "Higashiyama Line", "名城線": "Meijō Line", "名港線": "Meikō Line",
                "鶴舞線": "Tsurumai Line", "桜通線": "Sakura-dōri Line", "上飯田線": "Kamiiida Line"}
    names.update(lines_en)
    (OUT / "names_en.json").write_text(
        json.dumps({"names": names, "lines": lines_en, "trains": {}},
                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"nagoya: {len(stops)} stops, {len(names)} EN names -> {OUT}")


if __name__ == "__main__":
    main()
