#!/usr/bin/env python3
"""KRL Commuterline headway GTFS for Jakarta — config for headway_rail.build().

KAI/KRL provides schedules privately to Google/Apple but publishes no open
data, so this is a ROUGH headway model: KRL is a timetabled commuter network
with irregular branch frequencies, not a turn-up-and-go metro. Good for
"which line, roughly when, what fare"; the app's transfer/Google-Maps
handoffs cover precision. Fares: Rp3,000 first 25 km + Rp1,000 per 10 km.
Includes the premium Soekarno-Hatta airport rail link (own fare scale).
"""
from pathlib import Path

from headway_rail import build

ROOT = Path(__file__).resolve().parent.parent
KRL = [(25, 3000), (35, 4000), (45, 5000), (99, 6000)]
AIRPORT = [(20, 35000), (99, 70000)]
W = lambda mins: {"WK": [("04:30", "23:30", mins * 60)], "WE": [("04:30", "23:30", mins * 60)]}
LINES = {
    "B":  ("KB", "KRL Bogor", "Bogor Line (Jakarta Kota–Bogor)", 48, KRL, False, W(10)),
    "C":  ("KC", "KRL Cikarang", "Cikarang Loop Line", 46, KRL, False, W(15)),
    "R":  ("KR", "KRL Rangkasbitung", "Rangkasbitung Line (Tanah Abang–)", 48, KRL, False, W(20)),
    "T":  ("KT", "KRL Tangerang", "Tangerang Line (Duri–Tangerang)", 45, KRL, False, W(25)),
    "TP": ("KP", "KRL Tanjung Priok", "Tanjung Priok Line", 35, KRL, False, W(45)),
    "A":  ("KA", "Airport Railink", "Soekarno-Hatta Airport Line", 55, AIRPORT, False, W(30)),
}
# defaults unused (every line overrides) but required by the signature
WK = [("04:30", "23:30", 900)]

if __name__ == "__main__":
    build(ROOT / "data" / "raw" / "osm_jakarta_krl.json",
          ROOT / "data" / "raw" / "jakartakrl", LINES, WK, WK,
          ("KRL", "KRL Commuterline (headway model)",
           "https://commuterline.id", "Asia/Jakarta"), "IDR", "J")
