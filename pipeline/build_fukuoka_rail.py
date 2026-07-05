#!/usr/bin/env python3
"""Fukuoka City Subway headway GTFS — config for headway_rail.build().
Nishitetsu (the dominant bus operator) publishes no open GTFS and the subway
has none either, so Fukuoka v1 is a subway-first city on the headway model.
All three lines incl. the airport link (Kūkō line)."""
from pathlib import Path

from headway_rail import build

ROOT = Path(__file__).resolve().parent.parent
LADDER = [(3, 210), (7, 260), (11, 300), (15, 330), (99, 380)]
LINES = {
    "K": ("FK", "空港線",   "Kūkō (Airport) Line", 33, LADDER, False),
    "H": ("FH", "箱崎線",   "Hakozaki Line",       31, LADDER, False),
    "N": ("FN", "七隈線",   "Nanakuma Line",       32, LADDER, False),
}
WK = [("05:30", "07:00", 480), ("07:00", "09:00", 300), ("09:00", "17:00", 450),
      ("17:00", "19:00", 300), ("19:00", "24:00", 480)]
WE = [("05:30", "24:00", 480)]

if __name__ == "__main__":
    build(ROOT / "data" / "raw" / "osm_fukuoka_rail.json",
          ROOT / "data" / "raw" / "fukuokasubway", LINES, WK, WE,
          ("FKS", "Fukuoka City Subway (headway model)",
           "https://subway.city.fukuoka.lg.jp", "Asia/Tokyo"), "JPY", "F")
