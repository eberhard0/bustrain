#!/usr/bin/env python3
"""Tokyo Metro + JR Yamanote headway GTFS — config for headway_rail.build().
See headway_rail.py for the model rationale. Toei comes as real GTFS instead."""
from pathlib import Path

from headway_rail import build

ROOT = Path(__file__).resolve().parent.parent
METRO_LADDER = [(6, 180), (11, 210), (19, 260), (27, 300), (40, 330)]
JR_LADDER = [(3, 150), (6, 170), (10, 180), (15, 220), (25, 330)]
LINES = {
    "G":  ("MG", "銀座線",   "Ginza Line",      32, METRO_LADDER, False),
    "M":  ("MM", "丸ノ内線", "Marunouchi Line", 31, METRO_LADDER, False),
    "H":  ("MH", "日比谷線", "Hibiya Line",     31, METRO_LADDER, False),
    "T":  ("MT", "東西線",   "Tōzai Line",      36, METRO_LADDER, False),
    "C":  ("MC", "千代田線", "Chiyoda Line",    34, METRO_LADDER, False),
    "Y":  ("MY", "有楽町線", "Yūrakuchō Line",  34, METRO_LADDER, False),
    "Z":  ("MZ", "半蔵門線", "Hanzōmon Line",   34, METRO_LADDER, False),
    "N":  ("MN", "南北線",   "Namboku Line",    33, METRO_LADDER, False),
    "F":  ("MF", "副都心線", "Fukutoshin Line", 34, METRO_LADDER, False),
    "JY": ("JY", "山手線",   "Yamanote Line",   36, JR_LADDER,    True),
}
WK = [("05:00", "07:00", 360), ("07:00", "09:30", 180), ("09:30", "17:00", 300),
      ("17:00", "19:30", 240), ("19:30", "24:00", 360)]
WE = [("05:30", "24:00", 300)]

if __name__ == "__main__":
    build(ROOT / "data" / "raw" / "osm_tokyo_rail.json",
          ROOT / "data" / "raw" / "tokyometro", LINES, WK, WE,
          ("TKM", "Tokyo Metro / JR Yamanote (headway model)",
           "https://www.tokyometro.jp", "Asia/Tokyo"), "JPY", "K")
