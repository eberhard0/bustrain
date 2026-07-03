#!/usr/bin/env python3
"""Build bus-vs-train corridor comparison data for the 22 covered stations.

For every ordered station pair (A, B):
  bus:   median in-vehicle minutes + exact GTFS fare (yen), from trips that
         serve a bus stop of A and later a bus stop of B
  train: median in-vehicle minutes (local / express) mined from JR train
         itinerary pages, plus an approximate base fare from a distance ladder

Output: web/data/corridors.json
Run AFTER build_gtfs.py + fetch_jr.py (uses their raw caches).
"""
import csv
import json
import re
import statistics
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

from fetch_jr import STATIONS  # station code -> (name, lat, lon, lines)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
JR_CACHE = RAW / "jr"
TRAIN_CACHE = RAW / "jr_trains"
OUT = ROOT / "web" / "data" / "corridors.json"

FEEDS = ["oitabus", "oitakotsu", "kamenoibus"]
STATION_NAMES = [v[0] for v in STATIONS.values()]
COORD = {v[0]: (v[1], v[2]) for v in STATIONS.values()}

# JR Kyushu base fare ladder by km (approximate — post-2025 revision)
FARE_LADDER = [(3, 230), (6, 280), (10, 330), (15, 390), (20, 470), (25, 570),
               (30, 660), (35, 760), (40, 860), (45, 970), (50, 1040)]
EXP_SURCHARGE = [(25, 330), (50, 630), (75, 940)]  # unreserved ltd-exp, approx


def read_csv(feed, fname):
    p = RAW / feed / fname
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def hms_to_min(s):
    h, m, _ = s.split(":")
    return int(h) * 60 + int(m)


def station_bus_stops():
    """station name -> set of raw bus stop_ids per feed, matched by name prefix."""
    match = defaultdict(lambda: defaultdict(set))  # station -> feed -> {stop_id}
    names = defaultdict(set)
    for feed in FEEDS:
        for s in read_csv(feed, "stops.txt"):
            nm = s["stop_name"].strip()
            for st in STATION_NAMES:
                if nm.startswith(st + "駅"):
                    match[st][feed].add(s["stop_id"])
                    names[st].add(nm)
    return match, names


def bus_od(match):
    """ordered station pair -> {'min': median, 'fare': median_yen, 'n': trips}"""
    pair_times = defaultdict(list)
    pair_fares = defaultdict(list)
    pair_stops = defaultdict(list)
    for feed in FEEDS:
        stop_station = {}
        for st, feeds in match.items():
            for sid in feeds.get(feed, ()):
                stop_station[sid] = st
        if not stop_station:
            continue
        zones = {s["stop_id"]: s.get("zone_id") or s["stop_id"]
                 for s in read_csv(feed, "stops.txt")}
        trips = {t["trip_id"]: t["route_id"] for t in read_csv(feed, "trips.txt")}
        # fare lookup: (route_id, o_zone, d_zone) -> price
        price = {f["fare_id"]: int(float(f["price"])) for f in read_csv(feed, "fare_attributes.txt")}
        fare = {}
        for r in read_csv(feed, "fare_rules.txt"):
            fare[(r.get("route_id", ""), r.get("origin_id", ""), r.get("destination_id", ""))] = \
                price.get(r["fare_id"])
        by_trip = defaultdict(list)
        for st_row in read_csv(feed, "stop_times.txt"):
            if st_row["stop_id"] in stop_station:
                by_trip[st_row["trip_id"]].append(st_row)
        for tid, rows in by_trip.items():
            rows.sort(key=lambda r: int(r["stop_sequence"]))
            for i, a in enumerate(rows):
                for b in rows[i + 1:]:
                    sa, sb = stop_station[a["stop_id"]], stop_station[b["stop_id"]]
                    if sa == sb:
                        continue
                    try:
                        dt = hms_to_min(b["arrival_time"]) - hms_to_min(a["departure_time"])
                    except ValueError:
                        continue
                    if not 0 < dt <= 120:
                        continue
                    pair_times[(sa, sb)].append(dt)
                    pair_stops[(sa, sb)].append(
                        max(0, int(b["stop_sequence"]) - int(a["stop_sequence"]) - 1))
                    f = fare.get((trips.get(tid, ""), zones.get(a["stop_id"], ""),
                                  zones.get(b["stop_id"], "")))
                    if f:
                        pair_fares[(sa, sb)].append(f)
    out = {}
    for pair, times in pair_times.items():
        if len(times) < 3:
            continue
        entry = {"min": round(statistics.median(times)), "n": len(times),
                 "stops": round(statistics.median(pair_stops[pair]))}
        if pair_fares[pair]:
            entry["fare"] = int(statistics.median(pair_fares[pair]))
        out[pair] = entry
    return out


def harvest_train_links():
    """Collect train-detail URLs from cached weekday station pages."""
    links = set()
    for f in JR_CACHE.glob("*_20260703.html"):
        html = f.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'href="(/jr-k_time/\d{4}/\d{4}/\d+\.html)\?', html):
            links.add(m.group(1))
    return sorted(links)


def fetch_train(path):
    TRAIN_CACHE.mkdir(parents=True, exist_ok=True)
    cache = TRAIN_CACHE / (path.replace("/", "_") + ".html")
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")
    url = f"https://www.jrkyushu-timetable.jp{path}?c=28805&ym=202607&d=03"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="replace")
    cache.write_text(html, encoding="utf-8")
    time.sleep(1.2)
    return html


def parse_train(html):
    """Return (is_express, [(station, arr_min, dep_min)])."""
    kind_m = re.search(r"列車種\s*</td>\s*<td[^>]*>\s*([^<\s]+)", re.sub(r"<!--.*?-->", "", html, flags=re.S))
    kind = kind_m.group(1) if kind_m else "普通"
    is_exp = "特急" in kind
    text = re.sub(r"<[^>]+>", "|", html)
    text = re.sub(r"\|+", "|", text)
    rows = []
    for m in re.finditer(
            r"\|([^|\n]{1,10})\|[\s|]*(?:(\d{2}):(\d{2}) 着\|)?[\s|]*(?:(\d{2}):(\d{2}) 発|&nbsp;)",
            text):
        name = m.group(1).strip()
        if name not in COORD:
            continue
        arr = int(m.group(2)) * 60 + int(m.group(3)) if m.group(2) else None
        dep = int(m.group(4)) * 60 + int(m.group(5)) if m.group(4) else None
        rows.append((name, arr, dep))
    return is_exp, rows


def train_od(links, cap=150):
    pair = defaultdict(lambda: {"local": [], "exp": [], "localStops": [], "expStops": []})
    for path in links[:cap]:
        try:
            is_exp, rows = parse_train(fetch_train(path))
        except Exception as e:
            print("  skip", path, e)
            continue
        for i, (na, arra, depa) in enumerate(rows):
            if depa is None:
                continue
            for j, (nb, arrb, depb) in enumerate(rows[i + 1:], start=i + 1):
                t = (arrb if arrb is not None else depb)
                if t is None:
                    continue
                dt = t - depa
                if 0 < dt <= 150:
                    k = "exp" if is_exp else "local"
                    pair[(na, nb)][k].append(dt)
                    pair[(na, nb)][k + "Stops"].append(j - i - 1)
    out = {}
    for p, d in pair.items():
        e = {}
        if d["local"]:
            e["local"] = round(statistics.median(d["local"]))
            e["stopsL"] = round(statistics.median(d["localStops"]))
        if d["exp"]:
            e["exp"] = round(statistics.median(d["exp"]))
            e["stopsE"] = round(statistics.median(d["expStops"]))
        if e:
            out[p] = e
    return out


def km_between(a, b):
    import math
    (la, lo), (lb, lob) = COORD[a], COORD[b]
    t = math.pi / 180
    x = math.sin((lb - la) * t / 2) ** 2 + math.cos(la * t) * math.cos(lb * t) * \
        math.sin((lob - lo) * t / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(x)) * 1.2  # path factor


def ladder(km, table):
    for lim, yen in table:
        if km <= lim:
            return yen
    return table[-1][1]


def main():
    match, names = station_bus_stops()
    print("stations with bus stops:", {k: sorted(v)[:3] for k, v in list(names.items())[:5]}, "…")
    bus = bus_od(match)
    print(f"bus OD pairs: {len(bus)}")
    links = harvest_train_links()
    print(f"train detail links found: {len(links)} (fetching up to 150)")
    train = train_od(links)
    print(f"train OD pairs: {len(train)}")

    pairs = {}
    for (a, b) in set(bus) | set(train):
        e = {}
        if (a, b) in bus:
            e["bus"] = bus[(a, b)]
        if (a, b) in train:
            km = km_between(a, b)
            e["train"] = {**train[(a, b)], "fare": ladder(km, FARE_LADDER),
                          "expFare": ladder(km, FARE_LADDER) + ladder(km, EXP_SURCHARGE),
                          "km": round(km, 1)}
        pairs[f"{a}|{b}"] = e

    both = sum(1 for e in pairs.values() if "bus" in e and "train" in e)
    print(f"total pairs: {len(pairs)}, with both modes: {both}")
    data = {
        "stations": {st: {"lat": COORD[st][0], "lon": COORD[st][1],
                          "busStops": sorted(names.get(st, []))} for st in STATION_NAMES},
        "pairs": pairs,
        "notes": "Bus times/fares from GTFS (exact). Train times from JR itineraries. "
                 "Train fares approximate (distance ladder); Ltd-Exp fare incl. unreserved surcharge.",
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("->", OUT)


if __name__ == "__main__":
    main()
