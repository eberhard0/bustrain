#!/usr/bin/env python3
"""Parameterized GTFS -> BusTrain JSON builder (multi-city core).

Handles both timetabled feeds (explicit stop_times, e.g. Japanese GTFS-JP)
and frequency-based feeds (frequencies.txt headways, e.g. TransJakarta).

Per-stop departure row formats consumed by the client:
  timetabled:  [minute, route_short, headsign, pattern_id, stop_index]
  frequency:   [startMin, endMin, headwaySecs, route_short, headsign, pattern_id, stop_index]
               (length 7 marks a headway window; the client expands it)
"""
import csv
import json
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


def read_csv(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
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


def build_feed(feed_id, raw_dir, prefix, horizon_days=400):
    """Returns (stop_deps_by_name, stop_pos, dates_map, dt_labels, patterns)."""
    p = Path(raw_dir)
    cal = read_csv(p / "calendar.txt")
    cal_dates = read_csv(p / "calendar_dates.txt")
    stops = read_csv(p / "stops.txt")
    trips = read_csv(p / "trips.txt")
    stop_times = read_csv(p / "stop_times.txt")
    routes = {r["route_id"]: r for r in read_csv(p / "routes.txt")}
    freqs = defaultdict(list)
    for f in read_csv(p / "frequencies.txt"):
        freqs[f["trip_id"]].append(
            (hms_to_min(f["start_time"]), hms_to_min(f["end_time"]),
             int(f["headway_secs"])))

    # --- date -> active service set -> deduped day types ---
    weekday_cols = ["monday", "tuesday", "wednesday", "thursday", "friday",
                    "saturday", "sunday"]
    base, lo, hi = {}, None, None
    for r in cal:
        days = {i for i, c in enumerate(weekday_cols) if r[c] == "1"}
        s = date(int(r["start_date"][:4]), int(r["start_date"][4:6]), int(r["start_date"][6:]))
        e = date(int(r["end_date"][:4]), int(r["end_date"][4:6]), int(r["end_date"][6:]))
        base[r["service_id"]] = (days, s, e)
        lo = s if lo is None or s < lo else lo
        hi = e if hi is None or e > hi else hi
    exc = defaultdict(list)
    for r in cal_dates:
        d = date(int(r["date"][:4]), int(r["date"][4:6]), int(r["date"][6:]))
        exc[d].append((r["service_id"], r["exception_type"]))
        lo = d if lo is None or d < lo else lo
        hi = d if hi is None or d > hi else hi
    today = date.today()
    lo = max(lo or today, today - timedelta(days=1))
    hi = min(hi or today, today + timedelta(days=horizon_days))
    date_to_set = {}
    for d in daterange(lo, hi):
        active = {svc for svc, (days, s, e) in base.items() if s <= d <= e and d.weekday() in days}
        for svc, t in exc.get(d, []):
            (active.add if t == "1" else active.discard)(svc)
        date_to_set[d] = frozenset(active)
    set_to_dt, dt_sets, dates_map, dt_dates = {}, [], {}, defaultdict(list)
    for d, sset in date_to_set.items():
        if sset not in set_to_dt:
            set_to_dt[sset] = len(dt_sets)
            dt_sets.append(sset)
        dates_map[d.strftime("%Y%m%d")] = set_to_dt[sset]
        dt_dates[set_to_dt[sset]].append(d)
    dt_labels, used = {}, defaultdict(int)
    for dtid, ds in dt_dates.items():
        w = sum(1 for d in ds if d.weekday() < 5)
        s = sum(1 for d in ds if d.weekday() == 5)
        h = sum(1 for d in ds if d.weekday() == 6)
        lbl = {0: "Weekday", 1: "Saturday", 2: "Sun/Holiday"}[[w, s, h].index(max(w, s, h))]
        used[lbl] += 1
        dt_labels[str(dtid)] = lbl if used[lbl] == 1 else f"{lbl} {chr(64 + used[lbl])}"

    # --- stops, trips, patterns ---
    stop_meta = {}
    for s in stops:
        if s.get("location_type") == "1":
            continue
        try:
            stop_meta[s["stop_id"]] = (norm_name(s["stop_name"]),
                                       float(s["stop_lat"]), float(s["stop_lon"]))
        except (ValueError, KeyError):
            continue
    trip_info = {}
    for t in trips:
        r = routes.get(t["route_id"], {})
        trip_info[t["trip_id"]] = (r.get("route_short_name") or "", t["route_id"],
                                   t.get("trip_headsign") or "", t["service_id"])
    by_trip = defaultdict(list)
    for st in stop_times:
        by_trip[st["trip_id"]].append(st)

    stop_deps = defaultdict(list)   # name -> [(svc, row-without-svc)]
    stop_pos = defaultdict(list)
    pat_key_to_id, pat_offsets, pat_meta, pat_rep = {}, defaultdict(list), {}, {}
    for tid, rows in by_trip.items():
        if tid not in trip_info:
            continue
        short, route_id, t_head, svc = trip_info[tid]
        rows.sort(key=lambda r: int(r["stop_sequence"]))
        dest = stop_meta.get(rows[-1]["stop_id"], ("",))[0]
        named = []
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
            pat_key_to_id[pkey] = f"{prefix}{len(pat_key_to_id)}"
            pat_meta[pat_key_to_id[pkey]] = (short, [n[0] for n in named])
            pat_rep[pat_key_to_id[pkey]] = (route_id, [n[6] for n in named])
        pid = pat_key_to_id[pkey]
        t0 = named[0][1]
        pat_offsets[pid].append([n[1] - t0 for n in named])
        trip_start = hms_to_min(rows[0]["departure_time"] or rows[0]["arrival_time"])
        windows = freqs.get(tid)
        for i, (name, m, head, boardable, lat, lon, _sid) in enumerate(named):
            if not boardable:
                continue
            stop_pos[name].append((lat, lon))
            if windows:  # frequency service: one window row per (stop, window)
                off = m - trip_start
                for (ws, we, hw) in windows:
                    stop_deps[name].append((svc, [ws + off, we + off, hw, short, head, pid, i]))
            else:
                stop_deps[name].append((svc, [m, short, head, pid, i]))

    patterns = {}
    for pid, (short, names) in pat_meta.items():
        cols = list(zip(*pat_offsets[pid]))
        patterns[pid] = {"r": short, "s": names,
                         "o": [round(sorted(c)[len(c) // 2]) for c in cols]}

    # --- per-pattern fare matrix ---
    zones = {s["stop_id"]: s.get("zone_id") or s["stop_id"] for s in stops}
    price = {f["fare_id"]: int(float(f["price"])) for f in read_csv(p / "fare_attributes.txt")}
    frules = {}
    for r in read_csv(p / "fare_rules.txt"):
        frules[(r.get("route_id", ""), r.get("origin_id", ""),
                r.get("destination_id", ""))] = price.get(r["fare_id"])
    for pid, (rid, sids) in pat_rep.items():
        rows_f, any_fare = [], False
        for i in range(len(sids) - 1):
            row = []
            for j in range(i + 1, len(sids)):
                f = (frules.get((rid, zones.get(sids[i], ""), zones.get(sids[j], ""))) or
                     frules.get(("", zones.get(sids[i], ""), zones.get(sids[j], ""))) or
                     frules.get((rid, "", "")) or frules.get(("", "", "")) or 0)
                row.append(f)
                any_fare = any_fare or f > 0
            rows_f.append(row)
        if any_fare:
            patterns[pid]["f"] = rows_f

    return stop_deps, stop_pos, dt_sets, dates_map, dt_labels, patterns


def build_city(feeds, raw_root, out_dir, kind="bus"):
    """feeds: {feed_id: {name, name_en, color, prefix}}. Writes stops/, patterns.json
    and returns (stop_index, feed_meta, patterns)."""
    out = Path(out_dir)
    (out / "stops").mkdir(parents=True, exist_ok=True)
    all_stops, feed_meta, all_patterns = [], {}, {}
    for feed_id, cfg in feeds.items():
        deps, pos, dt_sets, dates_map, dt_labels, patterns = build_feed(
            feed_id, Path(raw_root) / feed_id, cfg["prefix"])
        all_patterns.update(patterns)
        count = 0
        for i, (name, entries) in enumerate(sorted(deps.items())):
            per_dt = {}
            for dtid, svcset in enumerate(dt_sets):
                rows = sorted([row for (svc, row) in entries if svc in svcset],
                              key=lambda x: x[0])
                if rows:
                    per_dt[str(dtid)] = rows
            if not per_dt:
                continue
            sid = f"{feed_id}_{i}"
            with open(out / "stops" / f"{sid}.json", "w", encoding="utf-8") as f:
                json.dump({"id": sid, "name": name, "kind": kind, "feed": feed_id,
                           "departures": per_dt}, f, ensure_ascii=False,
                          separators=(",", ":"))
            lats = [q[0] for q in pos[name]]
            lons = [q[1] for q in pos[name]]
            all_stops.append({"id": sid, "name": name, "kind": kind, "feed": feed_id,
                              "lat": round(sum(lats) / len(lats), 6),
                              "lon": round(sum(lons) / len(lons), 6),
                              "n": len(entries)})
            count += 1
        feed_meta[feed_id] = {k: v for k, v in cfg.items() if k != "prefix"}
        feed_meta[feed_id].update({"dates": dates_map, "dt_labels": dt_labels})
        print(f"{feed_id}: {count} named stops, {len(patterns)} patterns")
    with open(out / "patterns.json", "w", encoding="utf-8") as f:
        json.dump(all_patterns, f, ensure_ascii=False, separators=(",", ":"))
    return all_stops, feed_meta, all_patterns
