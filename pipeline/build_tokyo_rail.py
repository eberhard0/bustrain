#!/usr/bin/env python3
"""Generate a headway-based GTFS for Tokyo Metro (9 lines) + JR Yamanote loop.

Toei subway/bus come as REAL GTFS from ODPT's public endpoint; Tokyo Metro and
JR East publish full timetables only behind an ODPT developer key (roadmap).
Until then: station orders + coordinates + English names from OSM route
relations (cached in data/raw/osm_tokyo_rail.json), headways and fare ladders
from the operators' published figures. Both are turn-up-and-go systems
(trains every 2–6 min), so a frequency model is faithful in practice.

The Yamanote loop sequence is extended by half a lap so origin→destination
pairs crossing the list seam still route within a single linear pattern.

Output: data/raw/tokyometro/*.txt + names_en_extra.json
"""
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "raw" / "osm_tokyo_rail.json"
OUT = ROOT / "data" / "raw" / "tokyometro"

# ref -> (route_id, JP line name, EN line name, speed km/h, fare ladder, loop?)
METRO_LADDER = [(6, 180), (11, 210), (19, 260), (27, 300), (40, 330)]
JR_LADDER = [(3, 150), (6, 170), (10, 180), (15, 220), (25, 330)]
LINES = {
    "G":  ("MG",  "銀座線",   "Ginza Line",       32, METRO_LADDER, False),
    "M":  ("MM",  "丸ノ内線", "Marunouchi Line",  31, METRO_LADDER, False),
    "H":  ("MH",  "日比谷線", "Hibiya Line",      31, METRO_LADDER, False),
    "T":  ("MT",  "東西線",   "Tōzai Line",       36, METRO_LADDER, False),
    "C":  ("MC",  "千代田線", "Chiyoda Line",     34, METRO_LADDER, False),
    "Y":  ("MY",  "有楽町線", "Yūrakuchō Line",   34, METRO_LADDER, False),
    "Z":  ("MZ",  "半蔵門線", "Hanzōmon Line",    34, METRO_LADDER, False),
    "N":  ("MN",  "南北線",   "Namboku Line",     33, METRO_LADDER, False),
    "F":  ("MF",  "副都心線", "Fukutoshin Line",  34, METRO_LADDER, False),
    "JY": ("JY",  "山手線",   "Yamanote Line",    36, JR_LADDER,    True),
}

# WK: peak 3 min, base 5 min; WE: 5 min — representative of both operators
WK = [("05:00", "07:00", 360), ("07:00", "09:30", 180), ("09:30", "17:00", 300),
      ("17:00", "19:30", 240), ("19:30", "24:00", 360)]
WE = [("05:30", "24:00", 300)]


def hav_km(a, b, c, d):
    t = math.pi / 180
    return 2 * 6371 * math.asin(math.sqrt(
        math.sin((c - a) * t / 2) ** 2 +
        math.cos(a * t) * math.cos(c * t) * math.sin((d - b) * t / 2) ** 2))


def hms(m):
    return f"{m // 60:02d}:{m % 60:02d}:00"


def load_lines():
    """ref -> ordered [(jp_name, en_name, lat, lon)] — longest relation per ref."""
    d = json.loads(SRC.read_text(encoding="utf-8"))
    nodes = {e["id"]: e for e in d["elements"] if e["type"] == "node"}
    best = {}
    for r in (e for e in d["elements"] if e["type"] == "relation"):
        ref = r["tags"].get("ref", "")
        if ref not in LINES:
            continue
        seq = []
        for m in r["members"]:
            if m["type"] != "node" or "stop" not in m["role"]:
                continue
            n = nodes.get(m["ref"])
            if not n:
                continue
            t = n.get("tags", {})
            nm = t.get("name", "").strip()
            if not nm:
                continue
            if seq and seq[-1][0] == nm:
                continue
            seq.append((nm, t.get("name:en", "").replace(" Station", "").strip(),
                        n["lat"], n["lon"]))
        if len(seq) >= 2 and (ref not in best or len(seq) > len(best[ref])):
            best[ref] = seq
    return best


def fare_for(ladder, km):
    for cap, price in ladder:
        if km <= cap:
            return price
    return ladder[-1][1]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    lines = load_lines()
    missing = set(LINES) - set(lines)
    if missing:
        print("WARNING missing lines from OSM:", missing)
    stops, routes, trips, stop_times, freqs = [], [], [], [], []
    fare_attrs, fare_rules, names_en = {}, [], {}
    sid_of = {}
    for ref, seq in sorted(lines.items()):
        rid, jp, en, speed, ladder, loop = LINES[ref]
        routes.append({"route_id": rid, "agency_id": "TKM", "route_short_name": jp,
                       "route_long_name": f"{jp} {en}", "route_type": 1})
        names_en[jp] = en
        if loop:  # extend half a lap so seam-crossing OD pairs stay one-seat
            seq = seq + seq[:len(seq) // 2 + 1]
        for nm, enm, lat, lon in seq:
            if nm not in sid_of:
                sid = f"K{len(sid_of):03d}"
                sid_of[nm] = sid
                stops.append({"stop_id": sid, "stop_name": nm, "stop_lat": lat,
                              "stop_lon": lon, "zone_id": sid, "location_type": 0})
                if enm:
                    names_en[nm] = enm
        cum = [0.0]
        for i in range(1, len(seq)):
            km = hav_km(seq[i - 1][2], seq[i - 1][3], seq[i][2], seq[i][3]) * 1.2
            cum.append(cum[-1] + km / speed * 60 + 0.7)
        for direction, s2 in (("D0", seq), ("D1", list(reversed(seq)))):
            offs = cum if direction == "D0" else [cum[-1] - c for c in reversed(cum)]
            for svc, windows in (("WK", WK), ("WE", WE)):
                tid = f"{rid}-{direction}-{svc}"
                trips.append({"trip_id": tid, "route_id": rid, "service_id": svc,
                              "trip_headsign": s2[-1][0], "direction_id": direction[-1]})
                base = 5 * 60
                for k, (nm, _e, _la, _lo) in enumerate(s2):
                    m = base + round(offs[k])
                    stop_times.append({"trip_id": tid, "stop_sequence": k,
                                       "stop_id": sid_of[nm],
                                       "arrival_time": hms(m), "departure_time": hms(m),
                                       "pickup_type": 1 if k == len(s2) - 1 else 0,
                                       "drop_off_type": 0})
                for ws, we, hw in windows:
                    freqs.append({"trip_id": tid, "start_time": ws + ":00",
                                  "end_time": we + ":00", "headway_secs": hw,
                                  "exact_times": 0})
        # distance-ladder fares per ordered pair (unique station list, not the wrap)
        uniq = []
        for nm, _e, la, lo in seq:
            if nm not in [u[0] for u in uniq]:
                uniq.append((nm, la, lo))
        for i, (na, la1, lo1) in enumerate(uniq):
            for j, (nb, la2, lo2) in enumerate(uniq):
                if i == j:
                    continue
                km = hav_km(la1, lo1, la2, lo2) * (1.35 if loop else 1.25)
                price = fare_for(ladder, km)
                fid = f"F{price}"
                fare_attrs[fid] = price
                fare_rules.append({"fare_id": fid, "route_id": rid,
                                   "origin_id": sid_of[na], "destination_id": sid_of[nb]})
        print(f"  {ref:3s} {jp} — {len(uniq)} stations")

    def w(fname, rows, cols):
        with open(OUT / fname, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=cols)
            wr.writeheader()
            wr.writerows(rows)

    w("agency.txt", [{"agency_id": "TKM", "agency_name": "Tokyo Metro / JR Yamanote (headway model)",
                      "agency_url": "https://www.tokyometro.jp", "agency_timezone": "Asia/Tokyo"}],
      ["agency_id", "agency_name", "agency_url", "agency_timezone"])
    w("stops.txt", stops, ["stop_id", "stop_name", "stop_lat", "stop_lon", "zone_id", "location_type"])
    w("routes.txt", routes, ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type"])
    w("trips.txt", trips, ["trip_id", "route_id", "service_id", "trip_headsign", "direction_id"])
    w("stop_times.txt", stop_times,
      ["trip_id", "stop_sequence", "stop_id", "arrival_time", "departure_time", "pickup_type", "drop_off_type"])
    w("frequencies.txt", freqs, ["trip_id", "start_time", "end_time", "headway_secs", "exact_times"])
    w("calendar.txt", [
        {"service_id": "WK", "monday": 1, "tuesday": 1, "wednesday": 1, "thursday": 1,
         "friday": 1, "saturday": 0, "sunday": 0, "start_date": "20260101", "end_date": "20271231"},
        {"service_id": "WE", "monday": 0, "tuesday": 0, "wednesday": 0, "thursday": 0,
         "friday": 0, "saturday": 1, "sunday": 1, "start_date": "20260101", "end_date": "20271231"}],
      ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
       "sunday", "start_date", "end_date"])
    w("fare_attributes.txt",
      [{"fare_id": fid, "price": p, "currency_type": "JPY", "payment_method": 0, "transfers": ""}
       for fid, p in sorted(fare_attrs.items())],
      ["fare_id", "price", "currency_type", "payment_method", "transfers"])
    w("fare_rules.txt", fare_rules, ["fare_id", "route_id", "origin_id", "destination_id"])
    (OUT / "names_en_extra.json").write_text(
        json.dumps(names_en, ensure_ascii=False), encoding="utf-8")
    print(f"{len(stops)} stations, {len(trips)} trips, {len(fare_rules)} fare rules -> {OUT}")


if __name__ == "__main__":
    main()
