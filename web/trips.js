/* BusTrain — trips: destination compare verdict, optional login, history, savings.
   Loads after app.js and shares its top-level bindings. */
"use strict";

// Station order per line (partial network, enough to resolve direction/reach)
const LINES = {
  nippo: ["門司港", "門司", "小倉", "西小倉", "南小倉", "城野", "安部山公園", "下曽根", "朽網",
    "苅田", "小波瀬西工大前", "行橋", "南行橋", "新田原", "築城", "椎田", "豊前松江", "宇島",
    "三毛門", "吉富", "中津", "東中津", "今津", "天津", "豊前善光寺", "柳ケ浦", "豊前長洲",
    "宇佐", "西屋敷", "立石", "中山香", "杵築", "大神", "日出", "暘谷", "豊後豊岡", "亀川",
    "別府大学", "別府", "東別府", "西大分", "大分", "牧", "高城", "鶴崎", "大在", "坂ノ市",
    "幸崎", "佐志生", "下ノ江", "熊崎", "上臼杵", "臼杵", "津久見", "日代", "浅海井", "狩生",
    "海崎", "佐伯"],
  kyudai: ["大分", "古国府", "南大分", "賀来", "豊後国分", "向之原", "鬼瀬", "小野屋", "天神山",
    "庄内", "湯平", "南由布", "由布院", "野矢", "豊後中村", "恵良", "豊後森", "北山田", "天ケ瀬",
    "豊後中川", "日田", "久留米"],
  hohi: ["大分", "滝尾", "敷戸", "大分大学前", "中判田", "竹中", "犬飼", "菅尾", "三重町",
    "豊後清川", "緒方", "朝地", "豊後竹田", "宮地", "阿蘇", "立野", "肥後大津", "熊本"],
};

state.destPlace = JSON.parse(localStorage.getItem("bt_destplace") || "null");
state.vsPlace = JSON.parse(localStorage.getItem("bt_vsplace") || "null");
state.user = null;
state.history = [];
state.corridors = null;

async function loadCorridors() {
  // each file independently — one failed download must not empty the others
  const get = async (u, fb) => {
    try {
      const r = await fetch(u);
      if (!r.ok) throw new Error(String(r.status));
      return await r.json();
    } catch { return fb; }
  };
  const [cor, poi, pat] = await Promise.all([
    get("data/corridors.json", null),
    get("data/pois.json", null),
    get("data/patterns.json", null)]);
  if (cor) state.corridors = cor;
  else state.corridors = state.corridors || { pairs: {}, stations: {} };
  if (poi) state.pois = poi.pois || [];
  else state.pois = state.pois || [];
  if (pat) state.patterns = pat;
  else state.patterns = state.patterns || {};
  state._places = null; // rebuild place index with whatever arrived
}
async function ensureCorridors() {
  if (state.corridors && Object.keys(state.corridors.pairs || {}).length) return true;
  await loadCorridors(); // retry — e.g. a dropped LTE fetch on first load
  return Object.keys(state.corridors.pairs || {}).length > 0;
}

/* ---------- place search (tourist destinations) ---------- */
const KIND_ICO = { station: "🚉", stop: "🚏", onsen: "♨️", airport: "✈️", hospital: "🏥",
  university: "🎓", mall: "🛍️", museum: "🖼️", ferry: "⛴️", sight: "📍" };
function placeIndex() {
  if (state._places) return state._places;
  const out = [];
  for (const [name, st] of Object.entries(state.corridors?.stations || {}))
    out.push({ n: name + "駅", e: (en(name) || name) + " Station", lat: st.lat, lon: st.lon,
      k: "station", station: name });
  for (const p of state.pois || []) out.push(p);
  for (const s of state.index.stops)
    if (s.kind === "bus") out.push({ n: s.name, e: en(s.name), lat: s.lat, lon: s.lon, k: "stop" });
  state._places = out;
  return out;
}
const fold = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
function suggestPlaces(q) {
  q = fold(q.trim());
  if (!q) return [];
  const scored = [];
  for (const p of placeIndex()) {
    const jp = p.n.toLowerCase(), e = fold(p.e || "");
    let s = -1;
    if (jp.startsWith(q) || e.startsWith(q)) s = 0;
    else if (jp.includes(q) || e.includes(q)) s = 1;
    else {
      for (const [kjp, ken] of Object.entries(ALIAS))
        if (p.n.includes(kjp) && ken.includes(q)) { s = 2; break; }
    }
    if (s >= 0) scored.push([s + (p.k === "stop" ? 0.5 : 0), p]);
  }
  scored.sort((a, b) => a[0] - b[0]);
  return scored.slice(0, 8).map((x) => x[1]);
}
function nearestStationTo(lat, lon, excl) {
  let best = null;
  for (const [name, st] of Object.entries(state.corridors?.stations || {})) {
    if (name === excl) continue;
    const d = haversine(lat, lon, st.lat, st.lon);
    if (!best || d < best._d) best = { name, ...st, _d: d };
  }
  return best;
}

/* pattern-based bus routing: any origin point -> any destination point.
   originOverride restricts boarding to specific stops (home-tab picked stop). */
async function busViaPatterns(oLat, oLon, place, nowMin, tk, yk, originOverride) {
  const near = (lat, lon, radius, count) => state.index.stops
    .filter((s) => s.kind === "bus")
    .map((s) => ({ ...s, _d: haversine(lat, lon, s.lat, s.lon) }))
    .filter((s) => s._d <= radius)
    .sort((a, b) => a._d - b._d).slice(0, count);
  const originStops = originOverride
    ? originOverride.map((s) => ({ ...s, _d: haversine(oLat, oLon, s.lat, s.lon) }))
    : near(oLat, oLon, 700, 8);
  const destStops = near(place.lat, place.lon, 600, 6);
  if (!originStops.length || !destStops.length) return null;
  const destByName = new Map(destStops.map((s) => [s.name, s]));
  let best = null;
  for (const os of originStops) {
    const stop = await loadStop(os.id);
    const walk = walkMin(os._d);
    for (const d of upcoming(stop, 300, nowMin, tk, yk)) {
      if (best && d.m >= best.total) break; // later departures can't beat current best
      const pat = d.p && state.patterns[d.p];
      if (!pat) continue;
      for (let j = d.i + 1; j < pat.s.length; j++) {
        const ds = destByName.get(pat.s[j]);
        if (!ds) continue;
        const arr = d.m + pat.o[j] - pat.o[d.i];
        const finalWalk = walkMin(ds._d);
        if (!best || arr + finalWalk < best.total) {
          const fare = (pat.f && pat.f[d.i] && pat.f[d.i][j - d.i - 1]) || null;
          best = { total: arr + finalWalk, dep: d.m, arr, dur: arr - d.m, stops: j - d.i - 1,
            sign: d.h, signEn: en(d.h), label: `${d.r ? "[" + d.r + "] " : ""}from ${os.name}`,
            labelEn: `from ${en(os.name) || os.name}`,
            walk, lat: os.lat, lon: os.lon, boardAt: os.name, stopId: os.id,
            alightName: ds.name, alightLat: ds.lat, alightLon: ds.lon,
            finalWalk, finalDist: ds._d, fare };
        }
        break;
      }
    }
  }
  return best;
}

const stationOf = (stopName) => stopName.replace(/駅$/, "");
const ordinal = (n) => n + ({ 1: "st", 2: "nd", 3: "rd" }[n % 10 > 3 || (n % 100 >= 11 && n % 100 <= 13) ? 0 : n % 10] || "th");

/* the "how much do I save either way" note — both directions spelled out */
function savingsNote(bus, train, placeLabel, useTotals) {
  if (!bus || !train) return "";
  const tB = useTotals ? bus.total : bus.arr, tT = useTotals ? train.total : train.arr;
  const dt = tB - tT;                                     // >0 → train faster
  const dy = bus.fare && train.fare ? train.fare - bus.fare : null; // >0 → bus cheaper
  const min = (x) => `${Math.abs(x)} min`;
  const yen = (x) => `~¥${Math.abs(x)}`;
  const fareNote = dy === null ? `<br><small>(${!bus.fare ? "bus" : "train"} fare unknown — compare time only)</small>` : "";
  if (Math.abs(dt) <= 1) {
    return `🚌🚆 Both reach ${placeLabel} at about the same time` +
      (dy ? ` — <b>the ${dy > 0 ? "bus" : "train"} saves you ${yen(dy)}</b>.` : ".") + fareNote;
  }
  const fast = dt > 0 ? "train" : "bus", slow = dt > 0 ? "bus" : "train";
  const fastIco = fast === "bus" ? "🚌" : "🚆", slowIco = slow === "bus" ? "🚌" : "🚆";
  if (dy !== null && ((dy > 0 && fast === "bus") || (dy < 0 && fast === "train"))) {
    return `${fastIco} <b>The ${fast} wins both ways:</b> ${min(dt)} faster AND ${yen(dy)} cheaper.` + fareNote;
  }
  if (dy === null || dy === 0) {
    return `${fastIco} The ${fast} gets you to ${placeLabel} <b>${min(dt)} earlier</b>.` + fareNote;
  }
  const cheap = dy > 0 ? "bus" : "train";
  return `${fastIco} Take the <b>${fast}</b> → arrive <b>${min(dt)} earlier</b>, pay ${yen(dy)} more.<br>` +
    `${slowIco} Take the <b>${cheap}</b> → save <b>${yen(dy)}</b>, arrive ${min(dt)} later.` + fareNote;
}
function originStation() {
  const t = state.vs.train && stopMeta(state.vs.train.id);
  return t ? stationOf(t.name) : null;
}

/* shared place-search binding (home "Going to" + Search "To") */
function bindPlaceSearch(inputSel, suggSel, onPick) {
  const inp = $(inputSel), sugg = $(suggSel);
  inp.addEventListener("input", () => {
    const list = suggestPlaces(inp.value);
    sugg.classList.toggle("hidden", !list.length);
    sugg.innerHTML = list.map((p, i) => `<div class="sg" data-sg="${i}">
      <span class="ic">${KIND_ICO[p.k] || "📍"}</span>
      <div class="tx"><div class="jp">${esc(p.n)}</div>
        <div class="enl">${esc(p.e || en(p.n) || "")}</div></div></div>`).join("");
    sugg._list = list;
  });
  sugg.addEventListener("mousedown", (e) => {
    const sg = e.target.closest("[data-sg]");
    if (!sg) return;
    const p = sugg._list[parseInt(sg.dataset.sg, 10)];
    inp.value = `${p.n}${p.e ? " · " + p.e : ""}`;
    sugg.classList.add("hidden");
    onPick(p);
  });
  inp.addEventListener("blur", () => setTimeout(() => sugg.classList.add("hidden"), 250));
  inp.addEventListener("focus", () => { if (inp.value) inp.select(); });
}

/* --- does this departure go toward dest? --- */
function lineIdx(line, name) { return LINES[line] ? LINES[line].indexOf(name) : -1; }
function qualifiesTrain(headsign, o, d) {
  // headsign: "中山香行 · 日豊本線 行橋方面"
  const m = headsign.match(/^(.+?)行 · (\S+?)(?:本?線)? (\S+?)方面/);
  if (!m) return headsign.includes(d);
  const [, fin, lineName] = m;
  const line = lineName.includes("日豊") ? "nippo" : lineName.includes("久大") ? "kyudai" :
    lineName.includes("豊肥") ? "hohi" : null;
  if (!line) return headsign.includes(d);
  const io = lineIdx(line, o), id = lineIdx(line, d);
  if (io < 0 || id < 0) return false;
  const sign = Math.sign(id - io);
  const ifin = lineIdx(line, fin);
  if (ifin >= 0) return Math.sign(ifin - io) === sign && (ifin - id) * sign >= 0;
  // final stop beyond our list (博多, 宮崎空港…): trust the 方面 anchor direction
  const anchor = m[3] ? lineIdx(line, m[3]) : -1;
  return anchor >= 0 ? Math.sign(anchor - io) === sign : true;
}
const qualifiesBus = (headsign, d) => headsign.includes(d);

/* --- shared: next bus + next train from station area O toward D --- */
async function computeOptions(o, d) {
  const pair = state.corridors?.pairs[`${o}|${d}`];
  const dSt = state.corridors?.stations[d];
  const n = jstNow(), nowMin = n.h * 60 + n.mi, tk = dateKey(n), yk = prevDateKey(n);
  const geoWalk = (lat, lon) =>
    state.geo ? walkMin(haversine(state.geo.lat, state.geo.lon, lat, lon)) : 0;
  const options = {};
  if (pair && pair.train) {
    const tmeta = state.index.stops.find((s) => s.kind === "train" && s.name === o + "駅");
    if (tmeta) {
      const stop = await loadStop(tmeta.id);
      const rows = upcoming(stop, 40, nowMin, tk, yk).filter((r) => qualifiesTrain(r.h, o, d));
      const build = (nx) => {
        if (!nx) return null;
        const isExp = nx.r.startsWith("特急");
        const dur = (isExp ? pair.train.exp : pair.train.local) ?? pair.train.local ?? pair.train.exp;
        const sign = nx.h.split(" · ")[0]; // "大分行"
        return { dep: nx.m, arr: nx.m + dur, dur, label: `${nx.r} from ${tmeta.name}`,
          labelEn: `${enRoute(nx.r)} from ${en(tmeta.name) || tmeta.name}`,
          fare: isExp ? pair.train.expFare : pair.train.fare,
          walk: (state.vs.train?.id === tmeta.id && state.vs.train.walkMin) || geoWalk(tmeta.lat, tmeta.lon),
          stopId: tmeta.id, lat: tmeta.lat, lon: tmeta.lon, boardAt: tmeta.name,
          sign, signEn: `for ${en(sign.replace(/行$/, "")) || sign.replace(/行$/, "")}`,
          stops: isExp ? pair.train.stopsE : pair.train.stopsL };
      };
      // a Ltd.Exp costs a surcharge — only pick it if it beats the next local
      // by more than a few minutes
      const local = build(rows.find((r) => !r.r.startsWith("特急")));
      const exp = build(rows.find((r) => r.r.startsWith("特急")));
      options.train = local && exp ? (local.arr - exp.arr <= 6 ? local : exp) : (local || exp);
    }
  }
  if (dSt) {
    // bus leg via real route patterns — same engine as the journey planner
    const oSt = state.corridors.stations[o];
    const oLat = state.geo?.lat ?? oSt?.lat, oLon = state.geo?.lon ?? oSt?.lon;
    if (oLat != null) {
      const bus = await busViaPatterns(oLat, oLon, { n: d, lat: dSt.lat, lon: dSt.lon },
        nowMin, tk, yk);
      if (bus) options.bus = bus;
    }
  }
  return options;
}

/* --- verdict panel (home tab): picked stops -> any PLACE --- */
async function renderVerdict() {
  const box = $("#vs-verdict");
  await ensureCorridors();
  const p = state.vsPlace;
  const busPick = state.vs.bus && stopMeta(state.vs.bus.id);
  const trainPick = state.vs.train && stopMeta(state.vs.train.id);
  const inp = $("#vs-to-input");
  if (p && inp && !inp.value) inp.value = `${p.n}${p.e ? " · " + p.e : ""}`;
  if (!p || (!busPick && !trainPick)) { box.classList.add("hidden"); return; }
  const n = jstNow(), nowMin = n.h * 60 + n.mi, tk = dateKey(n), yk = prevDateKey(n);

  // train: picked station -> nearest covered station to the place + final walk
  let train = null;
  const o = originStation();
  if (o) {
    const s2 = nearestStationTo(p.lat, p.lon, o);
    if (s2 && s2._d <= 4000) {
      const co = await computeOptions(o, s2.name);
      if (co && co.train) {
        train = { ...co.train, alightName: s2.name + "駅", alightLat: s2.lat, alightLon: s2.lon,
          finalWalk: walkMin(s2._d), finalDist: s2._d };
        train.total = train.arr + train.finalWalk;
      }
    }
  }
  // bus: pattern routing from the picked stop's area (other poles of the
  // same station square count too — the right bus may leave across the street)
  let bus = null;
  if (busPick) {
    const area = state.index.stops
      .filter((s) => s.kind === "bus" &&
        haversine(busPick.lat, busPick.lon, s.lat, s.lon) <= 200)
      .slice(0, 8);
    bus = await busViaPatterns(busPick.lat, busPick.lon, p, nowMin, tk, yk,
      area.length ? area : [busPick]);
  }

  box.className = "verdict"; box.classList.remove("hidden");
  const pName = `${p.n} ${p.e || en(p.n) || ""}`.trim();
  if (!bus && !train) {
    box.innerHTML = `No more departures toward <b>${esc(pName)}</b> today from your picked stops.`;
    state.lastOptions = null;
    return;
  }
  const line = (side, x) => x
    ? `${side === "bus" ? "🚌" : "🚆"} <b>${fmtMin(x.dep)} → ~${fmtMin(x.total ?? x.arr)}</b> at ${esc(p.n)}
       · get off ${esc(x.alightName || "")}${x.finalWalk ? ` + 🚶 ${x.finalWalk} min` : ""}
       · ${x.fare ? "~¥" + x.fare : "fare n/a"}`
    : `${side === "bus" ? "🚌" : "🚆"} no option today`;
  const note = savingsNote(bus, train, esc(p.n), true);
  box.innerHTML = `To <b>${esc(pName)}</b>:<br>${note}${note ? "<br>" : ""}${line("bus", bus)}<br>${line("train", train)}
    <div class="take">
      ${bus ? '<button class="tb" data-take="bus">🚌 I’m taking the bus</button>' : ""}
      ${train ? '<button class="tt" data-take="train">🚆 I’m taking the train</button>' : ""}
    </div>`;
  state.lastOptions = { o: o || (busPick ? busPick.name : ""), d: p.n, options: { bus, train } };
}

/* --- journey planner (Search tab) --- */
function journeyOrigins() {
  const names = Object.keys(state.corridors?.stations || {})
    .filter((o) => Object.keys(state.corridors.pairs).some((k) => k.startsWith(o + "|")));
  if (state.geo) {
    names.sort((a, b) => {
      const A = state.corridors.stations[a], B = state.corridors.stations[b];
      return haversine(state.geo.lat, state.geo.lon, A.lat, A.lon) -
             haversine(state.geo.lat, state.geo.lon, B.lat, B.lon);
    });
  } else names.sort();
  return names;
}
function resolveOrigin() {
  const v = $("#j-from").value;
  if (v !== "loc") return v;
  if (!state.geo) return null;
  return journeyOrigins()[0] || null;
}
async function renderJourney() {
  if (!(await ensureCorridors())) {
    $("#j-status").textContent = "⚠️ Route data didn't load (weak connection?) — pull down to refresh.";
    $("#j-status").classList.remove("hidden");
    return;
  }
  const from = $("#j-from"), status = $("#j-status"), out = $("#j-results");
  // origins list (keep selection)
  const cur = from.value || localStorage.getItem("bt_jfrom") || "loc";
  from.innerHTML = '<option value="loc">📍 My location</option>' +
    journeyOrigins().map((o) =>
      `<option value="${o}" ${o === cur ? "selected" : ""}>${o} ${en(o)}</option>`).join("");
  if (cur === "loc") from.value = "loc";
  if (from.value === "loc" && !state.geo) {
    try { status.textContent = "📍 Finding you…"; status.classList.remove("hidden"); await getLocation(); }
    catch { status.textContent = "📍 Location unavailable — choose your starting station in “From”."; out.innerHTML = ""; return; }
  }
  const o = resolveOrigin();
  if (!o) { out.innerHTML = ""; return; }
  status.classList.add("hidden");
  const place = state.destPlace;
  const input = $("#j-to-input");
  if (place && !input.value) input.value = `${place.n}${place.e ? " · " + place.e : ""}`;
  if (!place) {
    out.innerHTML = `<div class="empty"><p>Starting near <b>${o} ${en(o)}</b>.</p>
      <p>Type where you want to go — a sight, onsen, the airport, a hospital,
      a station… and we'll pick the right stop for you.</p></div>`;
    return;
  }
  const n = jstNow(), nowMin = n.h * 60 + n.mi, tk = dateKey(n), yk = prevDateKey(n);
  const oSt = state.corridors.stations[o];
  const oLat = from.value === "loc" && state.geo ? state.geo.lat : oSt.lat;
  const oLon = from.value === "loc" && state.geo ? state.geo.lon : oSt.lon;
  out.innerHTML = `<div class="empty"><p>Finding the best bus and train…</p></div>`;

  // --- train: nearest covered station to the place, corridor times ---
  let train = null;
  const s2 = nearestStationTo(place.lat, place.lon, o);
  if (s2 && s2._d <= 4000) {
    const co = await computeOptions(o, s2.name);
    if (co && co.train) {
      train = { ...co.train, alightName: s2.name + "駅", alightLat: s2.lat, alightLon: s2.lon,
        finalWalk: walkMin(s2._d), finalDist: s2._d };
      train.total = train.arr + train.finalWalk;
    }
  }
  // --- bus: real route patterns to the stop nearest the place ---
  const bus = await busViaPatterns(oLat, oLon, place, nowMin, tk, yk);

  const placeName = `${place.n}${place.e ? " " + place.e : en(place.n) ? " " + en(place.n) : ""}`;
  if (!bus && !train) {
    out.innerHTML = `<div class="empty"><p>No more bus or train departures toward
      <b>${esc(placeName)}</b> today (or it's outside the covered area).</p></div>`;
    return;
  }
  state.lastOptions = { o, d: place.n, options: { bus, train } };
  const winner = bus && train ? (train.total <= bus.total ? "train" : "bus") : (bus ? "bus" : "train");
  const card = (side, x) => {
    if (!x) return `<div class="jres"><div class="jhead"><div class="mode ${side}">
      ${side === "bus" ? "🚌" : "🚆"}</div><div class="t">${side === "bus" ? "Bus" : "Train"}</div></div>
      <div class="jsub">No ${side} option toward ${esc(placeName)} today.</div></div>`;
    const inMin = x.dep - nowMin, leave = inMin - (x.walk || 0);
    return `<div class="jres ${side === winner ? "win" : ""}">
      <div class="jhead"><div class="mode ${side}">${side === "bus" ? "🚌" : "🚆"}</div>
        <div class="t">${side === "bus" ? "Bus" : "Train"}${side === winner ? " · best" : ""}</div></div>
      <div class="jbig"><b>${fmtMin(x.dep)}</b>
        <span class="in" style="color:${inMin <= 5 ? "var(--train)" : inMin <= 15 ? "var(--amber)" : "var(--bus)"}">
          in ${inMin} min</span></div>
      <div class="jmap" id="jmap-${side}"></div>
      <div class="jsub">${esc(x.label)}${x.labelEn ? ` <span class="ename" style="display:inline">${esc(x.labelEn)}</span>` : ""}<br>
        <span class="board">🪧 Board the ${side} signed <b>「${esc(x.sign)}」</b>${x.signEn ? ` · ${esc(x.signEn)}` : ""}</span><br>
        <span class="assure">✓ Get off at <b>${esc(x.alightName)}</b> ${esc(en(x.alightName))}
          — the <b>${ordinal((x.stops ?? 0) + 1)} stop</b>, ~${fmtMin(x.arr)}</span><br>
        then 🚶 ${x.finalWalk} min walk (${fmtDist(x.finalDist)}) →
        <b>arrive ${esc(place.n)} ~${fmtMin(x.total)}</b><br>
        ride ${x.dur} min${x.fare ? " · ~¥" + x.fare : ""}
        ${x.walk ? `<br><span class="leave">${leave < 0 ? "⚠ tight — " + x.walk + " min walk to the stop" :
          leave === 0 ? "🚶 leave NOW (" + x.walk + " min walk)" :
          "🚶 leave in " + leave + " min (" + x.walk + " min walk)"}</span>` : ""}
        ${x.lat ? `<br><button class="linkbtn guidebtn" data-guide="${x.lat},${x.lon}"
            data-guide-name="${esc(x.boardAt || "")}">🧭 Guide me to the stop</button>
          · <a class="maps" target="_blank" rel="noopener"
          href="https://www.google.com/maps/dir/?api=1&destination=${x.lat},${x.lon}&travelmode=walking">Google Maps</a>` : ""}
        ${x.alightLat != null && place.lat != null ? `<br><button class="linkbtn guidebtn"
            data-guide="${place.lat},${place.lon}" data-guide-name="${esc(place.n)}">
            🧭 After you get off: walk me to ${esc(place.n)}</button>` : ""}</div>
      <button class="jtake" style="background:var(--${side})" data-take="${side}">
        ${side === "bus" ? "🚌 I’m taking this bus" : "🚆 I’m taking this train"}</button>
    </div>`;
  };
  out.innerHTML =
    (bus && train ? `<div class="jwin-note">${savingsNote(bus, train, esc(place.n), true)}</div>` : "") +
    card("bus", bus) + card("train", train);
  drawJourneyMap("bus", bus, oLat, oLon, place);
  drawJourneyMap("train", train, oLat, oLon, place);
}

/* --- journey map: you → boarding stop → get-off stop → destination --- */
function drawJourneyMap(side, x, startLat, startLon, place) {
  const el = document.getElementById(`jmap-${side}`);
  if (!el || !x || typeof L === "undefined") { if (el) el.remove(); return; }
  if (el._map) el._map.remove();
  const map = L.map(el, { scrollWheelZoom: false, zoomControl: true });
  el._map = map;
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map);
  const color = side === "bus" ? "#0f9d58" : "#d93025";
  const pin = (emoji) => L.divIcon({ className: "pin", html: emoji, iconSize: [24, 24], iconAnchor: [12, 20] });
  const you = [startLat, startLon], board = [x.lat, x.lon];
  L.circleMarker(you, { radius: 8, color: "#fff", weight: 2, fillColor: "#1a73e8", fillOpacity: 1 })
    .addTo(map).bindPopup("📍 You are here");
  L.marker(board, { icon: pin(side === "bus" ? "🚏" : "🚉") }).addTo(map)
    .bindPopup(`Board here: ${x.boardAt} ${en(x.boardAt)}<br>🚶 ${x.walk || "?"} min walk`);
  L.polyline([you, board], { color: "#1a73e8", weight: 3, dashArray: "2 7" }).addTo(map);
  if (x.alightLat != null) {
    const alight = [x.alightLat, x.alightLon];
    L.marker(alight, { icon: pin("🎯") }).addTo(map)
      .bindPopup(`Get off: ${x.alightName} ${en(x.alightName)}`);
    L.polyline([board, alight], { color, weight: 4, opacity: 0.7 }).addTo(map);
    if (place && place.lat != null) {
      L.marker([place.lat, place.lon], { icon: pin("🏁") }).addTo(map)
        .bindPopup(`${place.n}${place.e ? " · " + place.e : ""}`);
      L.polyline([alight, [place.lat, place.lon]], { color: "#1a73e8", weight: 3, dashArray: "2 7" }).addTo(map);
    }
  }
  // open zoomed to the walk you need NOW (you -> boarding stop); zoom out to see it all
  map.fitBounds(L.latLngBounds([you, board]).pad(0.4), { maxZoom: 17 });
}

/* --- account --- */
async function apiJSON(url, opts = {}) {
  const r = await fetch(url, { headers: { "content-type": "application/json" }, ...opts });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    let msg = j.detail;
    if (Array.isArray(msg)) { // FastAPI validation errors: [{loc, msg, ...}, ...]
      msg = msg.map((e) => {
        const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : "";
        return `${field ? field + ": " : ""}${e.msg || "invalid"}`;
      }).join(" · ");
    }
    throw new Error(msg || "Request failed — please try again.");
  }
  return j;
}
async function fetchMe() {
  try { state.user = (await apiJSON("/api/me")).user; } catch { state.user = null; }
  if (state.user) await fetchHistory();
}
async function fetchHistory() {
  try {
    const j = await apiJSON("/api/history");
    state.history = j.items || [];
  } catch { state.history = []; }
}
function renderAccount() {
  const logged = !!state.user;
  $("#acct-forms").classList.toggle("hidden", logged);
  $("#acct-logged").classList.toggle("hidden", !logged);
  $("#acct-title").textContent = logged ? `Hi, ${state.user.username} 👋` : "Your account";
  $("#acct-sub").textContent = logged
    ? "Trips and history are being saved to your account."
    : "Log in to save trips & history across devices. Optional — without it nothing is stored.";
}

/* --- history + savings --- */
function renderHistory() {
  const list = $("#hist-list"), empty = $("#hist-empty"), stats = $("#stats-box");
  const trips = state.history.filter((h) => h.kind === "trip");
  empty.classList.toggle("hidden", trips.length > 0 || !state.user);
  if (!state.user) {
    list.innerHTML = `<div class="alert">🔒 Log in above to keep trip history — nothing is saved without an account.</div>`;
    stats.classList.add("hidden");
    return;
  }
  list.innerHTML = trips.map((h) => {
    const t = h.data, dtme = new Date(h.ts * 1000).toLocaleString("ja-JP",
      { timeZone: "Asia/Tokyo", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
    const alt = t.altArr != null
      ? ` · alt ${t.altMode === "bus" ? "🚌" : "🚆"} would arrive ${fmtMin(t.altArr)}${t.altFare ? " ~¥" + t.altFare : ""}`
      : "";
    return `<div class="hist-row">
      <div class="l1"><span>${t.mode === "bus" ? "🚌" : "🚆"} ${esc(t.from)} ${esc(en(t.from))}
        → ${esc(t.to)} ${esc(en(t.to))}</span>
        <span>${t.fare ? "~¥" + t.fare : ""}</span></div>
      <div class="l2">${dtme} · dep ${fmtMin(t.dep)} → arr ~${fmtMin(t.arr)}${alt}</div>
      <div class="actions">
        <button class="linkbtn" data-repeat="${h.id}">↻ Repeat this trip</button>
        <button class="linkbtn" style="color:#d93025" data-hdel="${h.id}">Delete</button>
      </div></div>`;
  }).join("");

  // savings: chosen vs alternative across all logged trips
  let yen = 0, mins = 0, nBoth = 0;
  for (const h of trips) {
    const t = h.data;
    if (t.altArr == null) continue;
    nBoth++;
    if (t.altFare && t.fare) yen += t.altFare - t.fare;
    mins += t.altArr - t.arr;
  }
  stats.classList.toggle("hidden", nBoth === 0);
  if (nBoth) {
    const money = yen >= 0 ? `saved <b>~¥${yen}</b>` : `spent <b>~¥${-yen}</b> extra`;
    const time = mins >= 0 ? `arrived <b>${mins} min</b> earlier in total` : `gave up <b>${-mins} min</b> in total`;
    stats.className = "stats";
    stats.innerHTML = `📊 <b>${trips.length} trips logged</b> (${nBoth} with a bus/train alternative).<br>
      Versus always taking the other option you ${money} and ${time}.`;
  }
}

async function logTrip(mode) {
  const lo = state.lastOptions || {};
  const opts = lo.options || {};
  const chosen = opts[mode], alt = opts[mode === "bus" ? "train" : "bus"];
  if (!chosen) return;
  const trip = {
    from: lo.o, to: lo.d, mode,
    dep: chosen.dep, arr: chosen.arr, fare: chosen.fare || null,
    altMode: mode === "bus" ? "train" : "bus",
    altDep: alt ? alt.dep : null, altArr: alt ? alt.arr : null, altFare: alt ? alt.fare : null,
    busStopId: opts.bus?.stopId || state.vs.bus?.id,
    trainStopId: opts.train?.stopId || state.vs.train?.id,
  };
  // get-off alert — works with or without an account; GPS-armed when possible.
  // Target the actual alighting stop when we know it (place-based journeys).
  const n = jstNow();
  const destSt = state.corridors?.stations[trip.to];
  const aLat = chosen.alightLat ?? (destSt ? destSt.lat : null);
  const aLon = chosen.alightLon ?? (destSt ? destSt.lon : null);
  const placePt = state.destPlace && state.destPlace.n === lo.d
    ? state.destPlace
    : (destSt ? { n: lo.d, lat: destSt.lat, lon: destSt.lon } : null);
  const arrRem = { type: "arrive", stopName: chosen.alightName || trip.to,
    m: chosen.arr, lead: 3,
    r: chosen.label, h: `Get off at ${chosen.alightName || trip.to}`, kind: mode,
    dateKey: dateKey(n), fired: false, lat: aLat, lon: aLon,
    placeName: placePt ? placePt.n : null,
    placeLat: placePt ? placePt.lat : null, placeLon: placePt ? placePt.lon : null };
  state.reminders.push(arrRem);
  save(); ensureNotifPermission(); renderReminders(); ensureGpsWatch();
  pushSchedule(arrRem); // background delivery for installed PWAs
  const alertMsg = `⏰📡 Get-off alert set: ${trip.to} ${en(trip.to)} ~${fmtMin(chosen.arr)}` +
    (destSt ? " · GPS watching" : "");
  if (!state.user) {
    toast(`${alertMsg} · log in (You tab) to also save this trip`, 5000);
    return;
  }
  try {
    await apiJSON("/api/history", { method: "POST", body: JSON.stringify({ kind: "trip", data: trip }) });
    await fetchHistory();
    toast(`${alertMsg} · trip logged`, 4000);
  } catch (e) { toast(e.message); }
}

function repeatTrip(id) {
  const h = state.history.find((x) => x.id === Number(id));
  if (!h) return;
  const t = h.data;
  if (t.busStopId && stopMeta(t.busStopId)) state.vs.bus = { id: t.busStopId, walkMin: null, dist: "" };
  if (t.trainStopId && stopMeta(t.trainStopId)) state.vs.train = { id: t.trainStopId, walkMin: null, dist: "" };
  const st = state.corridors?.stations[t.to];
  const pl = placeIndex().find((x) => x.n === t.to) ||
    (st ? { n: t.to, e: en(t.to), lat: st.lat, lon: st.lon, k: "station" } : null);
  if (pl) {
    state.vsPlace = pl;
    localStorage.setItem("bt_vsplace", JSON.stringify(pl));
    const inp = $("#vs-to-input");
    if (inp) inp.value = `${pl.n}${pl.e ? " · " + pl.e : ""}`;
  }
  save(); showTab("compare");
  toast(`↻ ${t.from} → ${t.to} loaded — pick your ride`);
}

/* --- events + init --- */
function initTrips() {
  bindPlaceSearch("#j-to-input", "#j-sugg", (p) => {
    state.destPlace = p;
    localStorage.setItem("bt_destplace", JSON.stringify(p));
    renderJourney();
  });
  bindPlaceSearch("#vs-to-input", "#vs-sugg", (p) => {
    state.vsPlace = p;
    localStorage.setItem("bt_vsplace", JSON.stringify(p));
    renderVerdict();
  });
  $("#j-from").addEventListener("change", (e) => {
    localStorage.setItem("bt_jfrom", e.target.value); renderJourney();
  });
  document.body.addEventListener("click", (e) => {
    const take = e.target.closest("[data-take]");
    const rep = e.target.closest("[data-repeat]");
    const hdel = e.target.closest("[data-hdel]");
    if (take) logTrip(take.dataset.take);
    else if (rep) repeatTrip(rep.dataset.repeat);
    else if (hdel) {
      apiJSON(`/api/history/${hdel.dataset.hdel}`, { method: "DELETE" })
        .then(fetchHistory).then(renderHistory).catch((err) => toast(err.message));
    }
  });
  const err = $("#acct-err");
  const creds = () => ({ username: $("#acct-user").value.trim(), password: $("#acct-pass").value });
  const validCreds = (c) => {
    if (!c.username) { err.textContent = "Please enter a username."; return false; }
    if (c.username.length < 2) { err.textContent = "Username needs at least 2 characters."; return false; }
    if (!/^[\w.\-@]+$/.test(c.username)) {
      err.textContent = "Username can only use letters, numbers and . - _ @"; return false;
    }
    if (c.password.length < 6) { err.textContent = "Password needs at least 6 characters."; return false; }
    return true;
  };
  $("#acct-login").addEventListener("click", async () => {
    err.textContent = "";
    if (!validCreds(creds())) return;
    try {
      state.user = { username: (await apiJSON("/api/login", { method: "POST", body: JSON.stringify(creds()) })).username };
      await fetchHistory(); renderAccount(); renderHistory(); toast(`Welcome back, ${state.user.username}!`);
    } catch (e2) { err.textContent = e2.message; }
  });
  $("#acct-register").addEventListener("click", async () => {
    err.textContent = "";
    if (!validCreds(creds())) return;
    try {
      state.user = { username: (await apiJSON("/api/register", { method: "POST", body: JSON.stringify(creds()) })).username };
      renderAccount(); renderHistory(); toast(`Account created — trips will now be saved.`);
    } catch (e2) { err.textContent = e2.message; }
  });
  $("#acct-logout").addEventListener("click", async () => {
    await apiJSON("/api/logout", { method: "POST" });
    state.user = null; state.history = [];
    renderAccount(); renderHistory(); toast("Logged out — nothing more will be saved.");
  });
  loadCorridors().then(() => { if (state.tab === "compare") renderVerdict(); });
  fetchMe().then(() => { renderAccount(); if (state.tab === "reminders") renderHistory(); });
}
initTrips();
