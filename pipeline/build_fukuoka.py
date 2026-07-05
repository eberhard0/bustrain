#!/usr/bin/env python3
"""Build the Fukuoka city dataset (subway-first: Nishitetsu publishes no open
GTFS, so v1 has no bus layer — cityMeta.bus=false hides bus UI).
Output: web/data/fukuoka/"""
import json
from datetime import date
from pathlib import Path

from gtfs_core import build_city

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "fukuoka"
RAW = ROOT / "data" / "raw"

FEEDS = {
    "fukuokasubway": {"name": "福岡市地下鉄", "name_en": "Fukuoka City Subway (headway model)",
                      "color": "#0080C5", "prefix": "fs", "kind": "train"},
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stops, feed_meta, _ = build_city(FEEDS, RAW, OUT)
    index = {"generated": date.today().isoformat(), "feeds": feed_meta, "stops": stops}
    (OUT / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (OUT / "corridors.json").write_text('{"pairs":{},"stations":{}}', encoding="utf-8")
    names = {}
    extra = RAW / "fukuokasubway" / "names_en_extra.json"
    if extra.exists():
        names.update(json.loads(extra.read_text(encoding="utf-8")))
    lines_en = {"空港線": "Kūkō (Airport) Line", "箱崎線": "Hakozaki Line", "七隈線": "Nanakuma Line"}
    names.update(lines_en)
    (OUT / "names_en.json").write_text(
        json.dumps({"names": names, "lines": lines_en, "trains": {}},
                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"fukuoka: {len(stops)} stops, {len(names)} EN names -> {OUT}")


if __name__ == "__main__":
    main()
