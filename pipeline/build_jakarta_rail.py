#!/usr/bin/env python3
"""Generate a headway-based GTFS feed for Jakarta rail (no official GTFS exists).

Covers MRT Jakarta North–South, LRT Jakarta, and LRT Jabodebek (both branches)
from their published operating hours, headways and fare rules. Station
coordinates are curated (station complexes are ~city-block sized; TODO refresh
from Overpass when the mirrors cooperate). Times between stations are
distance-derived — MRT/LRT here are turn-up-and-go systems and this generator
mirrors how the operators themselves publish service ("every 5–10 minutes").

Output: data/raw/jakartarail/*.txt  (consumed by build_jakarta.py via gtfs_core)
"""
import csv
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "jakartarail"

# (name, lat, lon) — north/west terminus first
MRT_NS = [
    ("Bundaran HI", -6.19300, 106.82310),
    ("Dukuh Atas BNI", -6.20080, 106.82270),
    ("Setiabudi Astra", -6.20900, 106.82190),
    ("Bendungan Hilir", -6.21520, 106.81780),
    ("Istora Mandiri", -6.22240, 106.80850),
    ("Senayan Mastercard", -6.22730, 106.80250),
    ("ASEAN", -6.23880, 106.79850),
    ("Blok M BCA", -6.24450, 106.79810),
    ("Blok A", -6.25560, 106.79720),
    ("Haji Nawi", -6.26670, 106.79710),
    ("Cipete Raya", -6.27820, 106.79730),
    ("Fatmawati Indomaret", -6.29250, 106.79350),
    ("Lebak Bulus Grab", -6.28950, 106.77450),
]
LRT_J = [
    ("Pegangsaan Dua", -6.14980, 106.91170),
    ("Boulevard Utara", -6.15400, 106.90810),
    ("Boulevard Selatan", -6.16220, 106.90570),
    ("Pulomas", -6.17570, 106.89390),
    ("Equestrian", -6.18320, 106.89430),
    ("Velodrome", -6.19160, 106.89170),
]
JBD_TRUNK = [
    ("Dukuh Atas", -6.20470, 106.82320),
    ("Setiabudi", -6.20940, 106.82970),
    ("Rasuna Said", -6.22120, 106.83180),
    ("Kuningan", -6.23070, 106.83050),
    ("Pancoran", -6.24230, 106.83790),
    ("Cikoko", -6.24450, 106.85360),
    ("Ciliwung", -6.24340, 106.86400),
    ("Cawang", -6.24600, 106.87130),
]
JBD_CBR = JBD_TRUNK + [
    ("TMII", -6.29170, 106.88090),
    ("Kampung Rambutan", -6.30810, 106.88400),
    ("Ciracas", -6.32360, 106.88690),
    ("Harjamukti", -6.37380, 106.89440),
]
JBD_BKS = JBD_TRUNK + [
    ("Halim", -6.24630, 106.88740),
    ("Jatibening Baru", -6.25660, 106.92840),
    ("Cikunir 1", -6.25720, 106.95300),
    ("Cikunir 2", -6.25850, 106.96640),
    ("Bekasi Barat", -6.25550, 106.99000),
    ("Jatimulya", -6.26480, 107.02170),
]

# windows: (start "HH:MM", end "HH:MM", headway seconds) per service id
WK_PEAK = [("05:00", "07:00", 600), ("07:00", "09:00", 300),
           ("09:00", "17:00", 600), ("17:00", "19:00", 300), ("19:00", "24:00", 600)]
WK_FLAT10 = [("05:30", "23:00", 600)]
WK_JBD = [("05:00", "22:30", 900)]
WE_MRT = [("06:00", "24:00", 600)]
WE_JBD = [("05:30", "22:00", 1200)]

LINES = [
    # (route_id, short, long, stations, speed_kmh, fare_fn, {svc: windows})
    ("MRT", "MRT", "MRT Jakarta North–South", MRT_NS, 34,
     lambda hops: min(3000 + 460 * hops, 8500),
     {"WK": WK_PEAK, "WE": WE_MRT}),
    ("LRTJ", "LRT", "LRT Jakarta (Kelapa Gading–Velodrome)", LRT_J, 30,
     lambda hops: 5000,
     {"WK": WK_FLAT10, "WE": WK_FLAT10}),
    ("JBDC", "LRT-CBR", "LRT Jabodebek (Dukuh Atas–Harjamukti)", JBD_CBR, 40,
     lambda hops: min(5000 + 500 * hops, 10000),
     {"WK": WK_JBD, "WE": WE_JBD}),
    ("JBDB", "LRT-BKS", "LRT Jabodebek (Dukuh Atas–Jatimulya)", JBD_BKS, 40,
     lambda hops: min(5000 + 500 * hops, 10000),
     {"WK": WK_JBD, "WE": WE_JBD}),
]


def hav_km(a, b, c, d):
    t = math.pi / 180
    return 2 * 6371 * math.asin(math.sqrt(
        math.sin((c - a) * t / 2) ** 2 +
        math.cos(a * t) * math.cos(c * t) * math.sin((d - b) * t / 2) ** 2))


def hms(m):
    return f"{m // 60:02d}:{m % 60:02d}:00"


def round100(x):
    return int(round(x / 100.0) * 100)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stops, routes, trips, stop_times, freqs, fare_attrs, fare_rules = [], [], [], [], [], {}, []
    sid_of = {}
    for rid, short, longname, stations, speed, fare_fn, svc_windows in LINES:
        routes.append({"route_id": rid, "agency_id": "JKR", "route_short_name": short,
                       "route_long_name": longname, "route_type": "1" if rid == "MRT" else "0"})
        for name, lat, lon in stations:
            if name not in sid_of:
                sid = f"R{len(sid_of):03d}"
                sid_of[name] = sid
                stops.append({"stop_id": sid, "stop_name": name, "stop_lat": lat,
                              "stop_lon": lon, "zone_id": sid, "location_type": "0"})
        # cumulative times (dwell 0.6 min per stop)
        cum = [0.0]
        for i in range(1, len(stations)):
            km = hav_km(stations[i - 1][1], stations[i - 1][2],
                        stations[i][1], stations[i][2]) * 1.15
            cum.append(cum[-1] + km / speed * 60 + 0.6)
        for direction, seq in (("D0", stations), ("D1", list(reversed(stations)))):
            offs = cum if direction == "D0" else [cum[-1] - c for c in reversed(cum)]
            for svc, windows in svc_windows.items():
                tid = f"{rid}-{direction}-{svc}"
                trips.append({"trip_id": tid, "route_id": rid, "service_id": svc,
                              "trip_headsign": seq[-1][0], "direction_id": direction[-1]})
                base = 5 * 60  # nominal; frequencies define real service
                for k, (name, lat, lon) in enumerate(seq):
                    m = base + round(offs[k])
                    stop_times.append({"trip_id": tid, "stop_sequence": k,
                                       "stop_id": sid_of[name],
                                       "arrival_time": hms(m), "departure_time": hms(m),
                                       "pickup_type": "1" if k == len(seq) - 1 else "0",
                                       "drop_off_type": "0"})
                for (ws, we, hw) in windows:
                    freqs.append({"trip_id": tid, "start_time": ws + ":00",
                                  "end_time": we + ":00", "headway_secs": hw,
                                  "exact_times": "0"})
        # fares for every ordered pair on this line
        for i, (na, _, _) in enumerate(stations):
            for j, (nb, _, _) in enumerate(stations):
                if i == j:
                    continue
                price = round100(fare_fn(abs(j - i) - 1 if abs(j - i) > 0 else 0))
                fid = f"F{price}"
                fare_attrs[fid] = price
                fare_rules.append({"fare_id": fid, "route_id": rid,
                                   "origin_id": sid_of[na], "destination_id": sid_of[nb]})

    def w(fname, rows, cols):
        with open(OUT / fname, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=cols)
            wr.writeheader()
            for r in rows:
                wr.writerow(r)

    w("agency.txt", [{"agency_id": "JKR", "agency_name": "MRT Jakarta / LRT (headway model)",
                      "agency_url": "https://jakartamrt.co.id", "agency_timezone": "Asia/Jakarta"}],
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
      [{"fare_id": fid, "price": p, "currency_type": "IDR", "payment_method": "0", "transfers": ""}
       for fid, p in sorted(fare_attrs.items())],
      ["fare_id", "price", "currency_type", "payment_method", "transfers"])
    w("fare_rules.txt", fare_rules, ["fare_id", "route_id", "origin_id", "destination_id"])
    print(f"generated {len(stops)} stations, {len(trips)} trips, {len(freqs)} windows, "
          f"{len(fare_rules)} fare rules -> {OUT}")


if __name__ == "__main__":
    main()
