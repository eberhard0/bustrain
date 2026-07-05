#!/usr/bin/env python3
"""Build web/data/names_en.json — Japanese name -> romaji/English.

Sources, in priority order:
  1. GTFS translations.txt `en` rows (official English, Ōita Bus / Ōita Kōtsū)
  2. GTFS translations.txt `ja-Hrkt` kana readings -> Hepburn romaji
  3. Hand-checked table for JR stations, train destinations and line names
Prints any JR headsign token still missing so gaps are visible.
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "web" / "data" / "beppu_oita" / "names_en.json"
FEEDS = ["oitabus", "oitakotsu", "kamenoibus"]

# --- kana -> Hepburn ---
K2R = {
 'きゃ':'kya','きゅ':'kyu','きょ':'kyo','しゃ':'sha','しゅ':'shu','しょ':'sho',
 'ちゃ':'cha','ちゅ':'chu','ちょ':'cho','にゃ':'nya','にゅ':'nyu','にょ':'nyo',
 'ひゃ':'hya','ひゅ':'hyu','ひょ':'hyo','みゃ':'mya','みゅ':'myu','みょ':'myo',
 'りゃ':'rya','りゅ':'ryu','りょ':'ryo','ぎゃ':'gya','ぎゅ':'gyu','ぎょ':'gyo',
 'じゃ':'ja','じゅ':'ju','じょ':'jo','びゃ':'bya','びゅ':'byu','びょ':'byo',
 'ぴゃ':'pya','ぴゅ':'pyu','ぴょ':'pyo','ふぁ':'fa','ふぃ':'fi','ふぇ':'fe','ふぉ':'fo',
 'あ':'a','い':'i','う':'u','え':'e','お':'o','か':'ka','き':'ki','く':'ku','け':'ke','こ':'ko',
 'さ':'sa','し':'shi','す':'su','せ':'se','そ':'so','た':'ta','ち':'chi','つ':'tsu','て':'te','と':'to',
 'な':'na','に':'ni','ぬ':'nu','ね':'ne','の':'no','は':'ha','ひ':'hi','ふ':'fu','へ':'he','ほ':'ho',
 'ま':'ma','み':'mi','む':'mu','め':'me','も':'mo','や':'ya','ゆ':'yu','よ':'yo',
 'ら':'ra','り':'ri','る':'ru','れ':'re','ろ':'ro','わ':'wa','ゐ':'i','ゑ':'e','を':'o',
 'が':'ga','ぎ':'gi','ぐ':'gu','げ':'ge','ご':'go','ざ':'za','じ':'ji','ず':'zu','ぜ':'ze','ぞ':'zo',
 'だ':'da','ぢ':'ji','づ':'zu','で':'de','ど':'do','ば':'ba','び':'bi','ぶ':'bu','べ':'be','ぼ':'bo',
 'ぱ':'pa','ぴ':'pi','ぷ':'pu','ぺ':'pe','ぽ':'po','ん':'n','ゔ':'vu',
 'ぁ':'a','ぃ':'i','ぅ':'u','ぇ':'e','ぉ':'o','・':' ','ー':'-','、':' ',
}


def kata_to_hira(s):
    return "".join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ヶ' else c for c in s)


def kana_to_romaji(kana):
    s = kata_to_hira(kana)
    out, i = [], 0
    while i < len(s):
        if s[i] == 'っ':
            nxt = s[i + 1:i + 3]
            r = K2R.get(nxt) or K2R.get(s[i + 1:i + 2], "")
            out.append(r[0] if r else "")
            i += 1
            continue
        two = s[i:i + 2]
        if two in K2R:
            out.append(K2R[two]); i += 2; continue
        one = s[i]
        if one in K2R:
            out.append(K2R[one])
        elif one.isascii():
            out.append(one)
        i += 1
    r = "".join(out)
    r = re.sub(r"([aeiou])-", r"\1\1", r)          # long vowel mark
    r = re.sub(r"n([bmp])", r"m\1", r)             # Hepburn n->m
    return r.capitalize()


JR_EN = {
    "亀川": "Kamegawa", "別府大学": "Beppu-Daigaku", "別府": "Beppu", "東別府": "Higashi-Beppu",
    "西大分": "Nishi-Ōita", "大分": "Ōita", "牧": "Maki", "高城": "Takajō", "鶴崎": "Tsurusaki",
    "大在": "Ōzai", "坂ノ市": "Sakanoichi", "幸崎": "Kōzaki", "古国府": "Furugō",
    "南大分": "Minami-Ōita", "賀来": "Kaku", "豊後国分": "Bungo-Kokubu", "向之原": "Mukainoharu",
    "滝尾": "Takio", "敷戸": "Shikido", "大分大学前": "Ōita-Daigaku-mae", "中判田": "Naka-Handa",
    "竹中": "Takenaka",
    # destinations / anchors beyond the covered area
    "博多": "Hakata", "小倉": "Kokura", "門司港": "Mojikō", "行橋": "Yukuhashi", "中津": "Nakatsu",
    "柳ケ浦": "Yanagigaura", "宇佐": "Usa", "杵築": "Kitsuki", "中山香": "Nakayamaga",
    "日出": "Hiji", "大神": "Ōga", "暘谷": "Yōkoku", "豊後豊岡": "Bungo-Toyooka",
    "佐伯": "Saiki", "臼杵": "Usuki", "津久見": "Tsukumi", "佐志生": "Sashiu", "下ノ江": "Shitanoe",
    "熊崎": "Kumazaki", "上臼杵": "Kami-Usuki", "日代": "Hishiro", "浅海井": "Azamui",
    "狩生": "Kariu", "海崎": "Kaizaki", "宮崎空港": "Miyazaki Airport", "宮崎": "Miyazaki",
    "南宮崎": "Minami-Miyazaki", "佐土原": "Sadowara", "延岡": "Nobeoka", "高鍋": "Takanabe",
    "熊本": "Kumamoto", "肥後大津": "Higo-Ōzu", "豊後竹田": "Bungo-Taketa", "三重町": "Miemachi",
    "犬飼": "Inukai", "菅尾": "Sugao", "緒方": "Ogata", "朝地": "Asaji", "豊後清川": "Bungo-Kiyokawa",
    "由布院": "Yufuin", "湯布院": "Yufuin", "日田": "Hita", "久留米": "Kurume",
    "豊後森": "Bungo-Mori", "天ケ瀬": "Amagase", "豊後中村": "Bungo-Nakamura", "庄内": "Shōnai",
    "小野屋": "Onoya", "鬼瀬": "Onigase", "湯平": "Yunohira", "南由布": "Minami-Yufu",
    "野矢": "Noya", "恵良": "Era", "北山田": "Kita-Yamada", "豊後中川": "Bungo-Nakagawa",
    "立石": "Tateishi", "西屋敷": "Nishi-Yashiki", "豊前長洲": "Buzen-Nagasu", "阿蘇": "Aso",
    "宮地": "Miyaji", "立野": "Tateno", "玉来": "Tamarai", "宇島": "Unoshima", "築城": "Tsuiki",
}
LINES_EN = {"日豊本線": "Nippō Line", "久大本線": "Kyūdai Line", "豊肥本線": "Hōhi Line"}
TRAIN_EN = {"普通": "Local", "快速": "Rapid", "特急": "Ltd.Exp", "ソニック": "Sonic",
            "にちりんシーガイア": "Nichirin Seagaia", "にちりん": "Nichirin",
            "九州横断特急": "Trans-Kyushu", "ゆふいんの森": "Yufuin no Mori", "ゆふ": "Yufu",
            "ひゅうが": "Hyūga", "きりしま": "Kirishima", "あそ": "Aso"}


def main():
    names = {}
    # kana first, then official en overwrites
    for feed in FEEDS:
        rows = list(csv.DictReader(open(RAW / feed / "translations.txt",
                                        encoding="utf-8-sig", newline="")))
        for r in rows:
            if r["lang"] == "ja-Hrkt" and r["trans_id"] not in names:
                names[r["trans_id"]] = kana_to_romaji(r["translation"])
        for r in rows:
            en = r["translation"].strip()
            en = re.sub(r"\s*\((Each|Both) Direction s?\)|\s*\((Each|Both) Directions?\)", "", en)
            if r["lang"] == "en" and en and en != "-1":
                names[r["trans_id"]] = en
    n_bus = len(names)

    names.update(JR_EN)
    names.update(LINES_EN)
    for st in list(JR_EN):
        names.setdefault(st + "駅", JR_EN[st] + " Sta.")

    # verify JR headsign coverage
    missing = set()
    for f in (ROOT / "web" / "data" / "beppu_oita" / "stops").glob("jr_*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        for rows in data["departures"].values():
            for _, _, h in rows:
                m = re.match(r"^(.+?)行 · (\S+?) (\S+?)方面$", h)
                if not m:
                    continue
                for token in (m.group(1), m.group(3)):
                    if token not in names:
                        missing.add(token)
    if missing:
        print("MISSING JR tokens:", sorted(missing))

    out = {"names": names, "lines": LINES_EN, "trains": TRAIN_EN}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{n_bus} bus names ({sum(1 for _ in names)} total) -> {OUT}")


if __name__ == "__main__":
    main()
