#!/usr/bin/env python3
"""Build web/data/pois.json — tourist landmarks in the Beppu/Ōita area from OSM.

A tourist searches "Umi Jigoku" or "airport", not a bus-stop name; each POI's
coordinates let the client pick the closest bus stop / station for them.
"""
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "pois.json"
CACHE = ROOT / "data" / "raw" / "osm_pois.json"

QUERY = """
[out:json][timeout:60];
(
  nwr["tourism"~"attraction|museum|aquarium|zoo|theme_park|viewpoint|gallery"]["name"](33.10,131.35,33.40,131.80);
  nwr["natural"="hot_spring"]["name"](33.10,131.35,33.40,131.80);
  nwr["leisure"="park"]["name"~"公園"](33.15,131.40,33.35,131.75);
  nwr["amenity"~"hospital|university"]["name"](33.10,131.35,33.40,131.80);
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
    if tags.get("amenity") == "hospital":
        return "hospital"
    if tags.get("amenity") == "university":
        return "university"
    if tags.get("amenity") == "ferry_terminal":
        return "ferry"
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
        if not name or name in seen:
            continue
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        if lat is None:
            continue
        seen.add(name)
        pois.append({"n": name, "e": t.get("name:en", ""), "lat": round(lat, 5),
                     "lon": round(lon, 5), "k": kind_of(t)})
    by_name = {p["n"]: p for p in pois}
    for n, e_name, lat, lon, k in MANUAL:
        if n in by_name:
            if not by_name[n]["e"]:
                by_name[n]["e"] = e_name  # OSM had no English name — use ours
        else:
            pois.append({"n": n, "e": e_name, "lat": lat, "lon": lon, "k": k})
            seen.add(n)
    OUT.write_text(json.dumps({"pois": pois}, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    with_en = sum(1 for p in pois if p["e"])
    print(f"{len(pois)} POIs ({with_en} with English names) -> {OUT}")


if __name__ == "__main__":
    main()
