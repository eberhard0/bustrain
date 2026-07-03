#!/usr/bin/env python3
"""Fetch JR Kyushu station departure timetables for Beppu/Oita-city stations
and emit the same per-stop JSON schema as build_gtfs.py.

Source: https://www.jrkyushu-timetable.jp/cgi-bin/jr-k_time/tt_dep.cgi?c=<code>&ym=YYYYMM&d=DD
The page is date-specific, so we fetch one weekday, one Saturday and one
Sunday and treat those as the three day types (0=weekday, 1=sat, 2=sun/hol).
Future dates are mapped to day types with a built-in JP national holiday list.

Run: python3 pipeline/fetch_jr.py            (fetches, throttled ~1 req/s)
"""
import json
import re
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data"
CACHE = ROOT / "data" / "raw" / "jr"

# station code -> (name, lat, lon, lines)  [coords from OpenStreetMap]
STATIONS = {
    28754: ("亀川",       33.33134, 131.49295, "日豊本線"),
    28806: ("別府大学",   33.31299, 131.49941, "日豊本線"),
    28805: ("別府",       33.27962, 131.50031, "日豊本線"),
    28788: ("東別府",     33.26774, 131.51057, "日豊本線"),
    28784: ("西大分",     33.24482, 131.58309, "日豊本線"),
    28742: ("大分",       33.23263, 131.60603, "日豊本線・久大本線・豊肥本線"),
    28807: ("牧",         33.23708, 131.63772, "日豊本線"),
    28770: ("高城",       33.24287, 131.65582, "日豊本線"),
    28776: ("鶴崎",       33.24276, 131.68696, "日豊本線"),
    28745: ("大在",       33.24399, 131.72031, "日豊本線"),
    28761: ("坂ノ市",     33.23675, 131.75195, "日豊本線"),
    28759: ("幸崎",       33.23335, 131.79536, "日豊本線"),
    28793: ("古国府",     33.22074, 131.6079,  "久大本線"),
    28809: ("南大分",     33.21416, 131.58585, "久大本線"),
    28751: ("賀来",       33.21297, 131.56229, "久大本線"),
    28798: ("豊後国分",   33.19478, 131.55096, "久大本線"),
    28811: ("向之原",     33.19668, 131.51408, "久大本線"),
    28771: ("滝尾",       33.20929, 131.62316, "豊肥本線"),
    28764: ("敷戸",       33.18783, 131.61528, "豊肥本線"),
    29381: ("大分大学前", 33.17692, 131.61911, "豊肥本線"),
    28782: ("中判田",     33.1641,  131.63881, "豊肥本線"),
    28772: ("竹中",       33.1213,  131.64947, "豊肥本線"),
}

# representative dates for each day type (must be within current dia)
SAMPLE_DATES = {0: date(2026, 7, 3), 1: date(2026, 7, 4), 2: date(2026, 7, 5)}

HOLIDAYS = {
    # 2026
    "20260101", "20260112", "20260211", "20260223", "20260320",
    "20260429", "20260503", "20260504", "20260505", "20260506",
    "20260720", "20260811", "20260921", "20260922", "20260923",
    "20261012", "20261103", "20261123",
    # 2027
    "20270101", "20270111", "20270211", "20270223", "20270321", "20270322",
    "20270429", "20270503", "20270504", "20270505", "20270719",
    "20270811", "20270920", "20270923", "20271011", "20271103", "20271123",
}

CELL_RE = re.compile(
    r'<td class=back5[^>]*>\s*<font size="1"(?P<color>[^>]*)>(?P<head>.*?)'
    r'<a href="[^"]*"[^>]*><b>(?P<min>\d{1,2})</b></a>\s*</font>\s*<br>\s*'
    r'(?P<dest>[^<\s][^<]*?)\s*</font>',
    re.S,
)
DIR_RE = re.compile(r'<div align="center" style="font-size:15px">([^<]+)</div>')
HOUR_RE = re.compile(r'<FONT COLOR="#FFFFFF">(\d{1,2})</FONT>')


def fetch(code, d):
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE / f"{code}_{d:%Y%m%d}.html"
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8", errors="replace")
    url = (f"https://www.jrkyushu-timetable.jp/cgi-bin/jr-k_time/tt_dep.cgi"
           f"?c={code}&ym={d:%Y%m}&d={d:%d}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="replace")
    cache_file.write_text(html, encoding="utf-8")
    time.sleep(1.2)
    return html


def parse(html):
    """Return [(minutes, route_label, headsign)] for one station+date."""
    deps = []
    # split into direction tables: each starts with the colspan=3 header div
    parts = re.split(r'<th align=center colspan="[23]"', html)
    for part in parts[1:]:
        mdir = DIR_RE.search(part)
        if not mdir:
            continue
        direction = mdir.group(1).strip()
        hour = None
        # walk the table row-wise: hour THs and back5 cells appear in order
        for m in re.finditer(
            r'<FONT COLOR="#FFFFFF">(\d{1,2})</FONT>|'
            r'<td class=back5[^>]*>\s*<font size="1"(?P<color>[^>]*)>(?P<head>.*?)'
            r'<a href="[^"]*"[^>]*><b>(?P<min>\d{1,2})</b></a>',
            part, re.S,
        ):
            if m.group(1) is not None:
                hour = int(m.group(1))
                continue
            if hour is None:
                continue
            # train name (express/rapid) sits before the minute link
            head_raw = re.sub(r"<[^>]+>", " ", m.group("head") or "")
            train = re.sub(r"\s+", " ", head_raw).strip()
            color = (m.group("color") or "").lower()
            if "red" in color:
                kind = "特急"
            elif "blue" in color:
                kind = "快速"
            else:
                kind = ""
            # destination: first text chunk after the closing </a>
            tail = part[m.end():m.end() + 400]
            mdest = re.search(r"<br>\s*([^<\s][^<]*?)\s*<", tail)
            dest = mdest.group(1).strip() if mdest else ""
            label = " ".join(x for x in (kind, train) if x)
            # "日豊本線 行橋・小倉・門司港方面（上り）" -> "日豊本線 行橋方面"
            dshort = re.sub(r"（.*?）", "", direction).strip()
            parts_d = dshort.split(" ", 1)
            if len(parts_d) == 2:
                dshort = f"{parts_d[0]} {parts_d[1].split('・')[0].replace('方面','')}方面"
            deps.append((hour * 60 + int(m.group("min")),
                         label or "普通",
                         f"{dest}行 · {dshort}"))
    deps.sort()
    return deps


def main():
    OUT.joinpath("stops").mkdir(parents=True, exist_ok=True)
    index_path = OUT / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))

    # date -> day type map for ~400 days
    dates_map = {}
    today = date.today()
    for i in range(400):
        d = today + timedelta(days=i)
        key = d.strftime("%Y%m%d")
        if key in HOLIDAYS or d.weekday() == 6:
            dates_map[key] = 2
        elif d.weekday() == 5:
            dates_map[key] = 1
        else:
            dates_map[key] = 0

    stops = [s for s in index["stops"] if s["feed"] != "jr"]
    for i, (code, (name, lat, lon, lines)) in enumerate(sorted(STATIONS.items())):
        per_dt = {}
        for dt, d in SAMPLE_DATES.items():
            rows = parse(fetch(code, d))
            if rows:
                per_dt[str(dt)] = [[m, r, h] for m, r, h in rows]
        sid = f"jr_{i}"
        with open(OUT / "stops" / f"{sid}.json", "w", encoding="utf-8") as f:
            json.dump({"id": sid, "name": f"{name}駅", "kind": "train", "feed": "jr",
                       "departures": per_dt}, f, ensure_ascii=False, separators=(",", ":"))
        n = sum(len(v) for v in per_dt.values())
        stops.append({"id": sid, "name": f"{name}駅", "kind": "train", "feed": "jr",
                      "lat": lat, "lon": lon, "n": n})
        print(f"{name}駅: {n} departures across day types")

    index["stops"] = stops
    index["feeds"]["jr"] = {"name": "JR九州", "name_en": "JR Kyushu",
                            "color": "#E50012", "dates": dates_map,
                            "dt_labels": {"0": "Weekday", "1": "Saturday", "2": "Sun/Holiday"}}
    index_path.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")),
                          encoding="utf-8")
    print(f"total stops: {len(stops)}")


if __name__ == "__main__":
    main()
