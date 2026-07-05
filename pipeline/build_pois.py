#!/usr/bin/env python3
"""Build web/data/pois.json — tourist landmarks in the Beppu/Ōita area from OSM.

A tourist searches "Umi Jigoku" or "airport", not a bus-stop name; each POI's
coordinates let the client pick the closest bus stop / station for them.
"""
import json
import re
import time
import urllib.request
from pathlib import Path

from build_names_en import kana_to_romaji

KANA_ONLY = re.compile(r"^[ぁ-んァ-ヶー・\s0-9A-Za-z！!?？&＆'’\-]+$")
HAS_KANA = re.compile(r"[ぁ-んァ-ヶ]")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "beppu_oita" / "pois.json"
CACHE = ROOT / "data" / "raw" / "osm_pois.json"

QUERY = """
[out:json][timeout:90];
(
  nwr["tourism"~"attraction|museum|aquarium|zoo|theme_park|viewpoint|gallery"]["name"](33.10,131.35,33.40,131.80);
  nwr["tourism"~"hotel|guest_house|hostel|ryokan"]["name"](33.10,131.35,33.40,131.80);
  nwr["natural"="hot_spring"]["name"](33.10,131.35,33.40,131.80);
  nwr["leisure"="park"]["name"~"公園"](33.15,131.40,33.35,131.75);
  nwr["amenity"~"hospital|university"]["name"](33.10,131.35,33.40,131.80);
  nwr["amenity"~"restaurant|cafe|fast_food|food_court|bar|pub|izakaya"]["name"](33.15,131.40,33.40,131.75);
  nwr["aeroway"="aerodrome"]["name"](33.30,131.60,33.60,131.80);
  nwr["shop"="mall"]["name"](33.10,131.35,33.40,131.80);
  nwr["amenity"="ferry_terminal"]["name"](33.10,131.35,33.40,131.80);
);
out center tags;
"""

# guarantee the classics even if OSM tagging is patchy
MANUAL = [
    ("海地獄", "Umi Jigoku (Sea Hell)", 33.3186, 131.4756, "onsen"),
    ("血の池地獄", "Chinoike Jigoku (Blood Pond Hell)", 33.3308, 131.4794, "onsen"),
    ("別府地獄めぐり", "Beppu Hells (Jigoku Meguri)", 33.3167, 131.4772, "onsen"),
    ("竹瓦温泉", "Takegawara Onsen", 33.2778, 131.5063, "onsen"),
    ("別府タワー", "Beppu Tower", 33.2823, 131.5051, "sight"),
    ("大分空港", "Ōita Airport", 33.4794, 131.7369, "airport"),
    ("アミュプラザおおいた", "Amu Plaza Ōita", 33.2331, 131.6067, "mall"),
    ("パークプレイス大分", "Park Place Ōita", 33.2103, 131.6620, "mall"),
    ("大分県立美術館", "Ōita Prefectural Art Museum (OPAM)", 33.2394, 131.6070, "museum"),
]


def fetch():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    req = urllib.request.Request("https://overpass-api.de/api/interpreter",
                                 data=QUERY.encode(), headers={"User-Agent": "bustrain-builder"})
    data = json.loads(urllib.request.urlopen(req, timeout=90).read())
    CACHE.write_text(json.dumps(data), encoding="utf-8")
    time.sleep(1)
    return data


def kind_of(tags):
    if tags.get("aeroway"):
        return "airport"
    if tags.get("natural") == "hot_spring":
        return "onsen"
    a = tags.get("amenity", "")
    if a == "hospital":
        return "hospital"
    if a == "university":
        return "university"
    if a == "ferry_terminal":
        return "ferry"
    if a in ("restaurant", "fast_food", "food_court", "izakaya"):
        return "food"
    if a == "cafe":
        return "cafe"
    if a in ("bar", "pub"):
        return "bar"
    if tags.get("tourism") in ("hotel", "guest_house", "hostel", "ryokan"):
        return "hotel"
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
        # dedupe by name AND ~250m grid cell — chains (Starbucks, Joyfull…)
        # keep one entry per branch, not one per brand
        key = (name, round(lat * 400), round(lon * 400))
        if key in seen:
            continue
        seen.add(key)
        en_name = t.get("name:en", "")
        if not en_name and HAS_KANA.search(name) and KANA_ONLY.match(name):
            en_name = kana_to_romaji(name)  # katakana shop names -> romaji
        pois.append({"n": name, "e": en_name, "lat": round(lat, 5),
                     "lon": round(lon, 5), "k": kind_of(t)})
    names_present = set()
    for n, e_name, lat, lon, k in MANUAL:
        hit = False
        for p in pois:
            if p["n"] == n:
                hit = True
                if not p["e"]:
                    p["e"] = e_name  # OSM had no English name — use ours
        if not hit:
            pois.append({"n": n, "e": e_name, "lat": lat, "lon": lon, "k": k})
    names_present.update(p["n"] for p in pois)
    OUT.write_text(json.dumps({"pois": pois}, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    with_en = sum(1 for p in pois if p["e"])
    print(f"{len(pois)} POIs ({with_en} with English names) -> {OUT}")


if __name__ == "__main__":
    main()
