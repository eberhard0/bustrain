#!/usr/bin/env python3
"""Fukuoka landmarks from OSM -> web/data/fukuoka/pois.json.

Sights, museums, malls and airports in the central wards. Hotels and
restaurants are left to the live Photon fallback — central Tokyo has far too
many to bundle offline.
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "fukuoka" / "pois.json"
CACHE = ROOT / "data" / "raw" / "osm_pois_fukuoka.json"

QUERY = """
[out:json][timeout:120];
(
  nwr["tourism"~"attraction|museum|aquarium|zoo|theme_park|viewpoint|gallery"]["name"](33.52,130.28,33.68,130.48);
  nwr["shop"="mall"]["name"](33.52,130.28,33.68,130.48);
  nwr["amenity"~"hospital|university"]["name"](33.54,130.30,33.66,130.46);
  nwr["aeroway"="aerodrome"]["name"](33.57,130.42,33.62,130.47);
);
out center tags;
"""

MANUAL = [
    ("キャナルシティ博多", "Canal City Hakata", 33.5899, 130.4108, "mall"),
    ("大濠公園", "Ōhori Park", 33.5861, 130.3760, "sight"),
    ("福岡タワー", "Fukuoka Tower", 33.5932, 130.3515, "sight"),
    ("福岡城跡", "Fukuoka Castle Ruins (Maizuru Park)", 33.5843, 130.3827, "sight"),
    ("櫛田神社", "Kushida Shrine", 33.5928, 130.4108, "sight"),
    ("東長寺", "Tōchō-ji Temple (Giant Buddha)", 33.5953, 130.4133, "sight"),
    ("博多駅", "Hakata Station area", 33.5902, 130.4207, "sight"),
    ("天神", "Tenjin district", 33.5914, 130.3989, "sight"),
    ("ベイサイドプレイス博多", "Bayside Place Hakata (ferry)", 33.6053, 130.4030, "sight"),
    ("マリンワールド海の中道", "Marine World Uminonakamichi", 33.6613, 130.4448, "sight"),
    ("福岡PayPayドーム", "Fukuoka PayPay Dome", 33.5953, 130.3620, "sight"),
    ("福岡空港", "Fukuoka Airport (FUK)", 33.5859, 130.4508, "airport"),
]


def fetch():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    req = urllib.request.Request("https://overpass.kumi.systems/api/interpreter",
                                 data=("data=" + urllib.parse.quote(QUERY)).encode(),
                                 headers={"User-Agent": "bustrain-builder"})
    data = json.loads(urllib.request.urlopen(req, timeout=180).read())
    CACHE.write_text(json.dumps(data), encoding="utf-8")
    time.sleep(1)
    return data


def kind_of(tags):
    if tags.get("aeroway"):
        return "airport"
    a = tags.get("amenity", "")
    if a == "hospital":
        return "hospital"
    if a == "university":
        return "university"
    if tags.get("shop") == "mall":
        return "mall"
    if tags.get("tourism") == "museum":
        return "museum"
    return "sight"


def main():
    data = fetch()
    pois, seen = [], set()
    for e in data["elements"]:
        t = e.get("tags", {})
        name = t.get("name")
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        if not name or lat is None:
            continue
        key = (name, round(lat * 400), round(lon * 400))
        if key in seen:
            continue
        seen.add(key)
        pois.append({"n": name, "e": t.get("name:en", ""), "lat": round(lat, 5),
                     "lon": round(lon, 5), "k": kind_of(t)})
    for n, e_name, lat, lon, k in MANUAL:
        hit = next((p for p in pois if p["n"] == n), None)
        if hit:
            if not hit["e"]:
                hit["e"] = e_name
        else:
            pois.append({"n": n, "e": e_name, "lat": lat, "lon": lon, "k": k})
    OUT.write_text(json.dumps({"pois": pois}, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"fukuoka: {len(pois)} POIs -> {OUT}")


if __name__ == "__main__":
    main()
