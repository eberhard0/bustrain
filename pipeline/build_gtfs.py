#!/usr/bin/env python3
"""Build compact per-stop departure JSON from the three Oita GTFS-JP feeds.

Input:  data/raw/{oitabus,oitakotsu,kamenoibus}/*.txt
Output: web/data/index.json                 (stop index + date->daytype map per feed)
        web/data/stops/<feed>_<n>.json      (departures per day-type for one named stop)

Day-type model: for every date in the feed validity window we resolve the
active service_ids (calendar + calendar_dates), then dedupe identical
service-sets into "day types". The client only needs today's day-type id.
"""
import csv
import json
import io
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "web" / "data" / "beppu_oita"

FEEDS = {
    "oitabus":    {"name": "大分バス",   "name_en": "Oita Bus",   "color": "#C8102E"},
    "oitakotsu":  {"name": "大分交通",   "name_en": "Oita Kotsu", "color": "#0072BC"},
    "kamenoibus": {"name": "亀の井バス", "name_en": "Kamenoi Bus","color": "#00A650"},
}

def read_csv(feed, fname):
    p = RAW / feed / fname
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def hms_to_min(s):
    h, m, _ = s.split(":")
    return int(h) * 60 + int(m)

def norm_name(s):
    return unicodedata.normalize("NFKC", s).strip()

def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)

def build_feed(feed):
    cal = read_csv(feed, "calendar.txt")
    cal_dates = read_csv(feed, "calendar_dates.txt")
    stops = read_csv(feed, "stops.txt")
    trips = read_csv(feed, "trips.txt")
    stop_times = read_csv(feed, "stop_times.txt")
    routes = {r["route_id"]: r for r in read_csv(feed, "routes.txt")}

    # --- resolve date -> frozenset(service_ids) ---
    weekday_cols = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    base = {}  # svc -> (days set, start, end)
    lo, hi = None, None
    for r in cal:
        days = {i for i, c in enumerate(weekday_cols) if r[c] == "1"}
        s = date(int(r["start_date"][:4]), int(r["start_date"][4:6]), int(r["start_date"][6:]))
        e = date(int(r["end_date"][:4]), int(r["end_date"][4:6]), int(r["end_date"][6:]))
        base[r["service_id"]] = (days, s, e)
        lo = s if lo is None or s < lo else lo
        hi = e if hi is None or e > hi else hi
    exc = defaultdict(list)  # date -> [(svc, type)]
    for r in cal_dates:
        d = date(int(r["date"][:4]), int(r["date"][4:6]), int(r["date"][6:]))
        exc[d].append((r["service_id"], r["exception_type"]))
        lo = d if lo is None or d < lo else lo
        hi = d if hi is None or d > hi else hi

    # cap the horizon at ~13 months to keep the map small
    hi = min(hi, lo + timedelta(days=400))
    date_to_set = {}
    for d in daterange(lo, hi):
        active = {svc for svc, (days, s, e) in base.items() if s <= d <= e and d.weekday() in days}
        for svc, t in exc.get(d, []):
            if t == "1":
                active.add(svc)
            else:
                active.discard(svc)
        date_to_set[d] = frozenset(active)

    # dedupe service-sets into day types
    set_to_dt = {}
    dt_sets = []
    dates_map = {}
    dt_dates = defaultdict(list)
    for d, s in date_to_set.items():
        if s not in set_to_dt:
            set_to_dt[s] = len(dt_sets)
            dt_sets.append(s)
        dates_map[d.strftime("%Y%m%d")] = set_to_dt[s]
        dt_dates[set_to_dt[s]].append(d)

    # human label per day type from the majority weekday class of its dates
    dt_labels = {}
    used = defaultdict(int)
    for dtid, ds in dt_dates.items():
        w = sum(1 for d in ds if d.weekday() < 5)
        s = sum(1 for d in ds if d.weekday() == 5)
        h = sum(1 for d in ds if d.weekday() == 6)
        base = {0: "Weekday", 1: "Saturday", 2: "Sun/Holiday"}[
            [w, s, h].index(max(w, s, h))]
        used[base] += 1
        dt_labels[str(dtid)] = base if used[base] == 1 else f"{base} {chr(64 + used[base])}"

    # --- trips ---
    trip_info = {}  # trip_id -> (route_short, route_id, trip_headsign, service_id)
    for t in trips:
        r = routes.get(t["route_id"], {})
        short = r.get("route_short_name") or ""
        trip_info[t["trip_id"]] = (short, t["route_id"], t.get("trip_headsign") or "", t["service_id"])

    # --- stop_times: group rows by trip to find final stop / headsigns ---
    stop_meta = {}  # stop_id -> (name, lat, lon)
    for s in stops:
        if s.get("location_type") in ("1",):  # parent stations: skip, poles carry times
            continue
        try:
            stop_meta[s["stop_id"]] = (norm_name(s["stop_name"]), float(s["stop_lat"]), float(s["stop_lon"]))
        except ValueError:
            continue

    by_trip = defaultdict(list)
    for st in stop_times:
        by_trip[st["trip_id"]].append(st)

    # named stop -> list of departures; route patterns for client-side routing
    stop_deps = defaultdict(list)   # name -> [(min, svc, route_short, headsign, pat_id, idx)]
    stop_pos = defaultdict(list)    # name -> [(lat, lon)]
    pat_key_to_id = {}
    pat_offsets = defaultdict(list)  # pat_id -> list of offset-lists (minutes from first stop)
    pat_meta = {}                    # pat_id -> (route_short, [stop names])
    pat_rep = {}                     # pat_id -> (route_id, [stop_ids]) for fare lookup
    for tid, rows in by_trip.items():
        if tid not in trip_info:
            continue
        short, route_id, t_head, svc = trip_info[tid]
        rows.sort(key=lambda r: int(r["stop_sequence"]))
        last_stop_id = rows[-1]["stop_id"]
        dest = stop_meta.get(last_stop_id, ("",))[0]
        named = []  # (name, minute, headsign, boardable, stop_id)
        for k, r in enumerate(rows):
            sid = r["stop_id"]
            if sid not in stop_meta:
                continue
            name, lat, lon = stop_meta[sid]
            try:
                m = hms_to_min(r["departure_time"] or r["arrival_time"])
            except (ValueError, AttributeError):
                continue
            head = r.get("stop_headsign") or t_head or dest
            boardable = k < len(rows) - 1 and r.get("pickup_type") != "1"
            named.append((name, m, head, boardable, lat, lon, sid))
        if len(named) < 2:
            continue
        pkey = (short, tuple(n[0] for n in named))
        if pkey not in pat_key_to_id:
            prefix = {"oitabus": "ob", "oitakotsu": "ok", "kamenoibus": "kb"}[feed]
            pat_key_to_id[pkey] = f"{prefix}{len(pat_key_to_id)}"
            pat_meta[pat_key_to_id[pkey]] = (short, [n[0] for n in named])
            pat_rep[pat_key_to_id[pkey]] = (route_id, [n[6] for n in named])
        pid = pat_key_to_id[pkey]
        t0 = named[0][1]
        pat_offsets[pid].append([n[1] - t0 for n in named])
        for i, (name, m, head, boardable, lat, lon, _sid) in enumerate(named):
            if not boardable:
                continue
            stop_deps[name].append((m, svc, short, head, pid, i))
            stop_pos[name].append((lat, lon))

    # median offsets per pattern
    patterns = {}
    for pid, (short, names) in pat_meta.items():
        cols = list(zip(*pat_offsets[pid]))
        patterns[pid] = {"r": short, "s": names,
                         "o": [round(sorted(c)[len(c) // 2]) for c in cols]}

    # fare matrix per pattern (triangular: f[i][j-i-1] = yen from stop i to j)
    zones = {s["stop_id"]: s.get("zone_id") or s["stop_id"] for s in stops}
    price = {f["fare_id"]: int(float(f["price"]))
             for f in read_csv(feed, "fare_attributes.txt")}
    frules = {}
    for r in read_csv(feed, "fare_rules.txt"):
        frules[(r.get("route_id", ""), r.get("origin_id", ""), r.get("destination_id", ""))] = \
            price.get(r["fare_id"])
    for pid, (rid, sids) in pat_rep.items():
        rows_f = []
        any_fare = False
        for i in range(len(sids) - 1):
            row = []
            for j in range(i + 1, len(sids)):
                f = frules.get((rid, zones.get(sids[i], ""), zones.get(sids[j], ""))) or \
                    frules.get(("", zones.get(sids[i], ""), zones.get(sids[j], ""))) or 0
                row.append(f)
                any_fare = any_fare or f > 0
            rows_f.append(row)
        if any_fare:
            patterns[pid]["f"] = rows_f

    # --- expand per day type, write per-stop files ---
    stop_index = []
    (OUT / "stops").mkdir(parents=True, exist_ok=True)
    for i, (name, deps) in enumerate(sorted(stop_deps.items())):
        lats = [p[0] for p in stop_pos[name]]
        lons = [p[1] for p in stop_pos[name]]
        sid = f"{feed}_{i}"
        per_dt = {}
        for dtid, svcset in enumerate(dt_sets):
            rows = sorted(
                [[m, s, h, pid, i] for (m, svc, s, h, pid, i) in deps if svc in svcset],
                key=lambda x: x[0],
            )
            if rows:
                per_dt[str(dtid)] = rows
        if not per_dt:
            continue
        with open(OUT / "stops" / f"{sid}.json", "w", encoding="utf-8") as f:
            json.dump({"id": sid, "name": name, "kind": "bus", "feed": feed,
                       "departures": per_dt}, f, ensure_ascii=False, separators=(",", ":"))
        stop_index.append({
            "id": sid, "name": name, "kind": "bus", "feed": feed,
            "lat": round(sum(lats) / len(lats), 6),
            "lon": round(sum(lons) / len(lons), 6),
            "n": len(deps),
        })
    return stop_index, dates_map, dt_labels, patterns


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    all_stops = []
    feed_meta = {}
    all_patterns = {}
    for feed, meta in FEEDS.items():
        idx, dates_map, dt_labels, patterns = build_feed(feed)
        all_stops.extend(idx)
        all_patterns.update(patterns)
        feed_meta[feed] = {**meta, "dates": dates_map, "dt_labels": dt_labels}
        print(f"{feed}: {len(idx)} named stops, {len(patterns)} patterns")
    with open(OUT / "patterns.json", "w", encoding="utf-8") as f:
        json.dump(all_patterns, f, ensure_ascii=False, separators=(",", ":"))
    index = {"generated": date.today().isoformat(), "feeds": feed_meta, "stops": all_stops}
    with open(OUT / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    print(f"total: {len(all_stops)} stops -> {OUT}")


if __name__ == "__main__":
    main()
