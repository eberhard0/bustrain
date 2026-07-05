#!/usr/bin/env python3
"""Nagoya Municipal Subway headway GTFS — config for headway_rail.build().
City bus is real GTFS-JP (BODIK); the subway publishes no GTFS, so its six
lines (incl. the Meijō loop) use the headway model from OSM route relations."""
from pathlib import Path

from headway_rail import build

ROOT = Path(__file__).resolve().parent.parent
LADDER = [(3, 210), (7, 240), (11, 270), (15, 310), (99, 340)]
LINES = {
    "H": ("NH", "東山線",   "Higashiyama Line", 32, LADDER, False),
    "M": ("NM", "名城線",   "Meijō Line",       32, LADDER, True),
    "E": ("NE", "名港線",   "Meikō Line",       32, LADDER, False),
    "T": ("NT", "鶴舞線",   "Tsurumai Line",    33, LADDER, False),
    "S": ("NS", "桜通線",   "Sakura-dōri Line", 33, LADDER, False),
    "K": ("NK", "上飯田線", "Kamiiida Line",    30, LADDER, False),
}
WK = [("05:30", "07:00", 600), ("07:00", "09:00", 300), ("09:00", "16:00", 450),
      ("16:00", "19:00", 300), ("19:00", "24:00", 600)]
WE = [("05:30", "24:00", 600)]

if __name__ == "__main__":
    build(ROOT / "data" / "raw" / "osm_nagoya_rail.json",
          ROOT / "data" / "raw" / "nagoyasubway", LINES, WK, WE,
          ("NGY", "Nagoya Municipal Subway (headway model)",
           "https://www.kotsu.city.nagoya.jp", "Asia/Tokyo"), "JPY", "N")
