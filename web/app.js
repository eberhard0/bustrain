/* BusTrain — Beppu & Ōita departure reminders. Vanilla JS, static data. */
"use strict";

const $ = (s) => document.querySelector(s);
const WALK_M_PER_MIN = 80; // Japanese real-estate walking standard
const ROUTE_FACTOR = 1.3;  // straight-line -> street distance

// EN aliases so an English speaker can search Japanese stop names
const ALIAS = {
  "亀川": "kamegawa", "別府大学": "beppudaigaku beppu university", "別府": "beppu",
  "東別府": "higashi beppu", "西大分": "nishi oita", "大分": "oita", "牧": "maki",
  "高城": "takajo", "鶴崎": "tsurusaki", "大在": "ozai", "坂ノ市": "sakanoichi",
  "幸崎": "kozaki", "古国府": "furugo", "南大分": "minami oita", "賀来": "kaku",
  "豊後国分": "bungo kokubu", "向之原": "mukainoharu", "滝尾": "takio", "敷戸": "shikido",
  "大分大学前": "oita university", "中判田": "nakahanda", "竹中": "takenaka",
  "鉄輪": "kannawa", "立命館": "apu ritsumeikan", "杉乃井": "suginoi",
  "由布院": "yufuin", "湯布院": "yufuin", "駅": "station eki",
  "地獄": "jigoku hell", "海地獄": "umi jigoku", "血の池": "chinoike",
  "空港": "airport kuko", "温泉": "onsen hot spring", "病院": "hospital byoin",
};

const state = {
  index: null,
  saved: JSON.parse(localStorage.getItem("bt_saved") || "[]"),
  reminders: JSON.parse(localStorage.getItem("bt_rem") || "[]"),
  lead: parseInt(localStorage.getItem("bt_lead") || "10", 10),
  vs: JSON.parse(localStorage.getItem("bt_vs") || "{}"), // {bus:{id,walkMin}, train:{id,walkMin}}
  stopCache: {},
  geo: null,
  tab: "compare",
  detailId: null,
  detailDay: null,
  searchKind: "all",
  vsPicking: null,
};

/* ---------- time (always JST) ---------- */
function jstNow() {
  const p = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Tokyo", year: "numeric",
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false }).formatToParts(new Date());
  const g = (t) => parseInt(p.find((x) => x.type === t).value, 10);
  return { y: g("year"), mo: g("month"), d: g("day"), h: g("hour") % 24, mi: g("minute"), s: g("second") };
}
const dateKey = (n) => `${n.y}${String(n.mo).padStart(2, "0")}${String(n.d).padStart(2, "0")}`;
function prevDateKey(n) {
  const d = new Date(Date.UTC(n.y, n.mo - 1, n.d));
  d.setUTCDate(d.getUTCDate() - 1);
  return `${d.getUTCFullYear()}${String(d.getUTCMonth() + 1).padStart(2, "0")}${String(d.getUTCDate()).padStart(2, "0")}`;
}
const fmtMin = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

/* ---------- data ---------- */
async function loadIndex() {
  const [r, rn] = await Promise.all([fetch("data/index.json"), fetch("data/names_en.json")]);
  state.index = await r.json();
  state.names = await rn.json().catch(() => null);
  $("#data-date").textContent = `Data built ${state.index.generated}.`;
}

/* ---------- English / romaji ---------- */
function en(jp) {
  if (!state.names || !jp) return "";
  const n = state.names.names;
  if (n[jp]) return n[jp];
  const stripped = jp.replace(/[（(].*?[）)]/g, "").trim();
  return n[stripped] || "";
}
function enRoute(r) { // "特急 ソニック 60" -> "Ltd.Exp Sonic 60"
  if (!state.names) return r;
  let out = r;
  for (const [jp, e] of Object.entries(state.names.trains)) out = out.split(jp).join(e);
  return out;
}
function pillText(r, kind) { // compact label for the colored pill
  if (kind !== "train") return r || "–";
  return enRoute(r).replace(/^Ltd\.Exp\s+(?=\S)/, "") || "–"; // "Sonic 11", "Local"
}
function enHeadsign(h, kind) {
  if (!state.names) return "";
  if (kind === "train") {
    const m = h.match(/^(.+?)行 · (\S+?) (\S+?)方面$/);
    if (m) {
      const line = state.names.lines[m[2]] || m[2];
      return `for ${en(m[1]) || m[1]} · ${line} (${en(m[3]) || m[3]} dir.)`;
    }
  }
  return en(h);
}
async function loadStop(id) {
  if (!state.stopCache[id]) {
    const r = await fetch(`data/stops/${id}.json`);
    state.stopCache[id] = await r.json();
  }
  return state.stopCache[id];
}
const stopMeta = (id) => state.index.stops.find((s) => s.id === id);
function dayType(feed, key) {
  const d = state.index.feeds[feed].dates;
  return d ? d[key] : undefined;
}
/* upcoming departures for a stop: today's remaining + yesterday's >24h times */
function upcoming(stop, n, nowMin, todayKey, yestKey) {
  const rows = [];
  const dtY = dayType(stop.feed, yestKey);
  if (dtY !== undefined && stop.departures[dtY]) {
    for (const [m, r, h, p, i] of stop.departures[dtY]) {
      if (m >= 1440 && m - 1440 >= nowMin) rows.push({ m: m - 1440, r, h, p, i });
    }
  }
  const dtT = dayType(stop.feed, todayKey);
  if (dtT !== undefined && stop.departures[dtT]) {
    for (const [m, r, h, p, i] of stop.departures[dtT]) {
      if (m >= nowMin && m < 1440) rows.push({ m, r, h, p, i });
    }
  }
  rows.sort((a, b) => a.m - b.m);
  return rows.slice(0, n);
}

/* ---------- persistence ---------- */
const save = () => {
  localStorage.setItem("bt_saved", JSON.stringify(state.saved));
  localStorage.setItem("bt_rem", JSON.stringify(state.reminders));
  localStorage.setItem("bt_lead", String(state.lead));
  localStorage.setItem("bt_vs", JSON.stringify(state.vs));
};

/* ---------- geo ---------- */
function haversine(a, b, c, d) {
  const R = 6371000, t = Math.PI / 180;
  const x = Math.sin(((c - a) * t) / 2) ** 2 +
    Math.cos(a * t) * Math.cos(c * t) * Math.sin(((d - b) * t) / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}
const walkMin = (meters) => Math.max(1, Math.round((meters * ROUTE_FACTOR) / WALK_M_PER_MIN));
const fmtDist = (m) => (m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`);
function getLocation() {
  return new Promise((res, rej) => {
    if (!navigator.geolocation) return rej(new Error("no geolocation"));
    navigator.geolocation.getCurrentPosition(
      (p) => { state.geo = { lat: p.coords.latitude, lon: p.coords.longitude }; res(state.geo); },
      (e) => rej(e), { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 });
  });
}

/* ---------- rendering helpers ---------- */
function pillClass(route, kind) {
  if (kind === "train") {
    if (route.startsWith("特急")) return "pill exp";
    if (route.startsWith("快速")) return "pill rapid";
    return "pill";
  }
  return "pill bus";
}
function countClass(inMin) { return inMin <= 5 ? "urgent" : inMin <= 15 ? "soon" : "ok"; }
const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function depRow(stop, d, nowMin, opts = {}) {
  const inMin = d.m - nowMin;
  const remOn = state.reminders.some((r) => r.stopId === stop.id && r.m === d.m && r.h === d.h && !r.fired);
  const enH = enHeadsign(d.h, stop.kind);
  return `<div class="dep ${opts.past ? "past" : ""}">
    <span class="${pillClass(d.r, stop.kind)}">${esc(pillText(d.r, stop.kind))}</span>
    <div class="info"><div class="dest">${esc(d.h)}</div>
      ${enH ? `<div class="ename">${esc(enH)}</div>` : ""}
      <div class="time">Scheduled ${fmtMin(d.m)}</div></div>
    ${opts.past ? "" : `<div class="count ${countClass(inMin)}"><b>${inMin} min</b><span>${fmtMin(d.m)}</span></div>`}
    <button class="bell ${remOn ? "on" : ""}" data-rem='${JSON.stringify({ stopId: stop.id, m: d.m, r: d.r, h: d.h }).replace(/'/g, "&#39;")}'>${remOn ? "🔔" : "🔕"}</button>
  </div>`;
}

function renderNextReminderBanner(nowMin, tk) {
  const el = $("#next-reminder");
  const up = state.reminders.filter((r) => !r.fired && r.dateKey === tk && r.m >= nowMin)
    .sort((a, b) => a.m - b.m)[0];
  if (!up) { el.classList.add("hidden"); return; }
  el.classList.remove("hidden");
  el.innerHTML = `🔔 Next reminder: <b>${esc(up.r)} ${esc(up.h)}</b> — alert at ${fmtMin(up.m - up.lead)} (${up.lead} min before ${fmtMin(up.m)})`;
}

/* ---------- search ---------- */
function searchStops(q, kind) {
  q = q.trim().toLowerCase();
  let list = state.index.stops;
  if (kind !== "all") list = list.filter((s) => s.kind === kind);
  if (q) {
    list = list.filter((s) => {
      if (s.name.toLowerCase().includes(q)) return true;
      for (const [jp, en] of Object.entries(ALIAS))
        if (s.name.includes(jp) && en.includes(q)) return true;
      return false;
    });
  }
  if (state.geo) {
    list = list.map((s) => ({ ...s, _d: haversine(state.geo.lat, state.geo.lon, s.lat, s.lon) }))
      .sort((a, b) => a._d - b._d);
  } else {
    list = [...list].sort((a, b) => b.n - a.n); // busiest first
  }
  return list.slice(0, 40);
}
function stopRowHTML(s, forPick) {
  const feed = state.index.feeds[s.feed];
  const starred = state.saved.includes(s.id);
  const dist = s._d !== undefined ? `<div class="dist">${fmtDist(s._d)}<br>${walkMin(s._d)} min walk</div>` : "";
  return `<div class="row" data-${forPick ? "pick" : "open"}="${s.id}">
    <div class="mode ${s.kind}">${s.kind === "train" ? "🚆" : "🚌"}</div>
    <div class="titles"><div class="name">${esc(s.name)}</div>
      <div class="sub">${en(s.name) ? esc(en(s.name)) + " · " : ""}${feed.name_en}</div></div>${dist}
    ${forPick ? "" : `<button class="star ${starred ? "on" : ""}" data-star="${s.id}">${starred ? "★" : "☆"}</button>`}
  </div>`;
}
function renderSearch() {
  // picking a stop for the compare tab -> classic stop list; otherwise journey planner
  const picking = !!state.vsPicking;
  $("#stop-search").classList.toggle("hidden", !picking);
  $("#journey").classList.toggle("hidden", picking);
  if (!picking) {
    if (typeof renderJourney === "function") renderJourney();
    return;
  }
  const q = $("#search-input").value;
  const list = searchStops(q, state.vsPicking);
  $("#search-results").innerHTML = list.map((s) => stopRowHTML(s, true)).join("") ||
    `<div class="empty"><p>No stops match.</p></div>`;
}

/* ---------- nearby ---------- */
async function renderNearby() {
  try {
    $("#nearby-status").textContent = "📍 Locating…";
    await getLocation();
    const list = state.index.stops
      .map((s) => ({ ...s, _d: haversine(state.geo.lat, state.geo.lon, s.lat, s.lon) }))
      .sort((a, b) => a._d - b._d).slice(0, 25);
    $("#nearby-status").textContent = "📍 Closest stops to you:";
    $("#nearby-results").innerHTML = list.map((s) => stopRowHTML(s)).join("");
  } catch (e) {
    $("#nearby-status").textContent = "📍 Couldn't get your location — allow location access and retry.";
  }
}

/* ---------- compare (bus vs train) — the home tab ---------- */
async function renderCompare() {
  const nb = jstNow();
  renderNextReminderBanner(nb.h * 60 + nb.mi, dateKey(nb));
  updateNotifBanner();
  const bus = state.vs.bus && stopMeta(state.vs.bus.id);
  const train = state.vs.train && stopMeta(state.vs.train.id);
  $("#vs-bus-name").textContent = bus ? `${bus.name} ${en(bus.name)}` : "Tap to choose…";
  $("#vs-train-name").textContent = train ? `${train.name} ${en(train.name)}` : "Tap to choose…";
  $("#vs-bus-walk").textContent = bus && state.vs.bus.walkMin != null
    ? `${state.vs.bus.dist} · ~${state.vs.bus.walkMin} min walk` : "";
  $("#vs-train-walk").textContent = train && state.vs.train.walkMin != null
    ? `${state.vs.train.dist} · ~${state.vs.train.walkMin} min walk` : "";
  const cols = $("#vs-cols");
  if (!bus || !train) { cols.classList.add("hidden"); return; }
  cols.classList.remove("hidden");
  $("#vs-bus-head").textContent = bus.name.length > 9 ? bus.name.slice(0, 9) + "…" : bus.name;
  $("#vs-train-head").textContent = train.name;

  const n = jstNow(), nowMin = n.h * 60 + n.mi, tk = dateKey(n), yk = prevDateKey(n);
  $("#vs-hint").classList.remove("hidden");
  // when a destination is set, the columns only show departures going THAT way
  const p = state.vsPlace;
  let busDestNames = null, trainO = null, trainDest = null;
  if (p && state.patterns && typeof nearestStationTo === "function") {
    busDestNames = new Set(state.index.stops
      .filter((s) => s.kind === "bus" && haversine(p.lat, p.lon, s.lat, s.lon) <= 600)
      .map((s) => s.name));
    trainO = originStation();
    const s2 = trainO ? nearestStationTo(p.lat, p.lon, trainO) : null;
    trainDest = s2 && s2._d <= 4000 ? s2.name : null;
  }
  $("#vs-hint").textContent = p
    ? `🧭 Showing only departures toward ${p.n}${p.e ? " " + p.e : ""} — tap one to set its reminder and walk there`
    : "🧭 Tap a departure to set its reminder and get walking directions to the stop";
  for (const side of ["bus", "train"]) {
    const cfg = state.vs[side];
    const meta = stopMeta(cfg.id);
    const stop = await loadStop(cfg.id);
    let rows = upcoming(stop, 40, nowMin, tk, yk);
    if (side === "bus" && busDestNames) {
      rows = rows.filter((d) => {
        const pat = d.p && state.patterns[d.p];
        if (!pat) return false;
        for (let j = d.i + 1; j < pat.s.length; j++) if (busDestNames.has(pat.s[j])) return true;
        return false;
      });
    } else if (side === "train" && trainO && trainDest && trainDest !== trainO) {
      rows = rows.filter((d) => qualifiesTrain(d.h, trainO, trainDest));
    }
    rows = rows.slice(0, 5);
    const w = cfg.walkMin || 0;
    const guideAttrs = meta
      ? `data-guide="${meta.lat},${meta.lon}" data-guide-name="${esc(meta.name)} ${esc(en(meta.name))}"`
      : "";
    $(`#vs-${side}-list`).innerHTML = rows.map((d) => {
      const inMin = d.m - nowMin;
      const leaveIn = inMin - w;
      const missed = leaveIn < 0;
      const leaveTxt = w
        ? (missed ? "⚠ can't make it on foot" : leaveIn === 0 ? "🚶 leave NOW" : `🚶 leave in ${leaveIn} min (${fmtMin(d.m - w)})`)
        : "";
      const kind = side === "train" ? "train" : "bus";
      const enH = enHeadsign(d.h, kind);
      const autorem = JSON.stringify({ stopId: cfg.id, m: d.m, r: d.r, h: d.h }).replace(/'/g, "&#39;");
      return `<div class="vdep ${missed ? "missed" : countClass(inMin)}" ${guideAttrs}
          data-autorem='${autorem}'>
        <div class="l1"><b>${fmtMin(d.m)}</b><span class="in">${inMin} min 🧭</span></div>
        <div class="l2">${esc(kind === "train" ? enRoute(d.r) : d.r)} · ${esc(d.h)}</div>
        ${enH ? `<div class="l2 ename">${esc(enH)}</div>` : ""}
        ${leaveTxt ? `<div class="leave">${leaveTxt}</div>` : ""}
      </div>`;
    }).join("") || `<div class="vdep"><div class="l2">${p ? `No more departures toward ${esc(p.n)} from here today.` : "No more departures today."}</div></div>`;
  }
  if (typeof renderVerdict === "function") renderVerdict();
}
async function vsAutoPick() {
  $("#vs-status").textContent = "📍 Locating…";
  try {
    await getLocation();
    for (const kind of ["bus", "train"]) {
      const ranked = state.index.stops.filter((s) => s.kind === kind)
        .map((s) => ({ ...s, _d: haversine(state.geo.lat, state.geo.lon, s.lat, s.lon) }))
        .sort((a, b) => a._d - b._d);
      // among poles at essentially the same corner, prefer the BUSY one —
      // the nearest pole can be a 4-departures-a-day variant
      const near = ranked.filter((s) => s._d <= ranked[0]._d + 120);
      const best = near.sort((a, b) => b.n - a.n)[0] || ranked[0];
      state.vs[kind] = { id: best.id, walkMin: walkMin(best._d), dist: fmtDist(best._d) };
    }
    save();
    $("#vs-status").textContent = "⚖️ Nearest options — walk time is already factored into “leave in”. ";
    renderCompare();
  } catch { $("#vs-status").textContent = "📍 Couldn't get location — pick stops manually below."; }
}

/* ---------- reminders ---------- */
function renderReminders() {
  $("#lead-select").value = String(state.lead);
  const list = $("#rem-list");
  const items = state.reminders.filter((r) => !r.fired).sort((a, b) => a.m - b.m);
  $("#rem-empty").classList.toggle("hidden", items.length > 0);
  $("#rem-count").classList.toggle("hidden", items.length === 0);
  $("#rem-count").textContent = items.length;
  list.innerHTML = items.map((r, i) => `<div class="row">
    <div class="mode ${r.kind}">${r.kind === "train" ? "🚆" : "🚌"}</div>
    <div class="titles"><div class="name">${r.type === "arrive"
        ? `🎯 ${fmtMin(r.m)} get off at ${esc(r.stopName)} ${esc(en(r.stopName))}`
        : `${fmtMin(r.m)} ${esc(r.kind === "train" ? enRoute(r.r) : r.r)} · ${esc(r.h)}`}</div>
      <div class="sub">${r.type === "arrive"
        ? `Arrival alert ~${fmtMin(r.m - r.lead)}${r.lat != null
            ? ` · 📡 GPS armed — fires within ${(GPS_RADIUS[r.kind] || 400)} m of your stop (keep BusTrain open)`
            : ""}`
        : `${esc(r.stopName)} ${esc(en(r.stopName))} — alert ${r.lead} min before (${fmtMin(r.m - r.lead)})`}</div></div>
    ${r.type === "arrive" && (r.placeLat ?? r.lat) != null
      ? `<button class="star" title="Walk me there"
           data-guide="${r.placeLat ?? r.lat},${r.placeLon ?? r.lon}"
           data-guide-name="${esc(r.placeName || r.stopName)}">🧭</button>` : ""}
    <button class="star on" data-del="${state.reminders.indexOf(r)}">✕</button>
  </div>`).join("");
}
function toggleReminder(payload) {
  const n = jstNow(), tk = dateKey(n);
  const i = state.reminders.findIndex((r) => r.stopId === payload.stopId && r.m === payload.m && r.h === payload.h && !r.fired);
  if (i >= 0) {
    const [removed] = state.reminders.splice(i, 1);
    pushCancel(removed);
    toast("Reminder removed");
  } else {
    const meta = stopMeta(payload.stopId);
    const rem = { ...payload, stopName: meta.name, kind: meta.kind, lead: state.lead,
      dateKey: tk, fired: false };
    state.reminders.push(rem);
    toast(`🔔 Reminder set — ${state.lead} min before ${fmtMin(payload.m)}`);
    ensureNotifPermission();
    pushSchedule(rem);
  }
  save(); refresh();
}
/* set a reminder if one doesn't already exist (one-gesture row taps) */
function ensureReminder(payload) {
  const tk = dateKey(jstNow());
  const exists = state.reminders.some((r) => r.stopId === payload.stopId &&
    r.m === payload.m && r.h === payload.h && r.dateKey === tk); // fired ones count too
  if (exists) return false;
  const meta = stopMeta(payload.stopId);
  if (!meta) return false;
  const rem = { ...payload, stopName: meta.name, kind: meta.kind, lead: state.lead,
    dateKey: tk, fired: false };
  state.reminders.push(rem);
  save(); ensureNotifPermission(); pushSchedule(rem); renderReminders();
  return true;
}

function ensureNotifPermission() {
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission().then(() => ensurePush());
  }
}

/* ---------- web push: reminders that work with the app CLOSED ----------
   iOS 16.4+: only for Home-Screen-installed web apps. Android/desktop: any. */
let pushSubCache = null;
function b64ToU8(b64) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const s = (b64 + pad).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}
async function ensurePush() {
  try {
    if (!("PushManager" in window) || !("serviceWorker" in navigator)) return null;
    if (Notification.permission !== "granted") return null;
    if (pushSubCache) return pushSubCache;
    const reg = await navigator.serviceWorker.ready;
    pushSubCache = await reg.pushManager.getSubscription();
    if (!pushSubCache) {
      const k = await (await fetch("/api/push/key")).json();
      if (!k.enabled) return null;
      pushSubCache = await reg.pushManager.subscribe(
        { userVisibleOnly: true, applicationServerKey: b64ToU8(k.key) });
    }
    return pushSubCache;
  } catch { return null; }
}
function reminderEpoch(r) { // JST dateKey+minutes -> epoch seconds of the ALERT time
  const y = +r.dateKey.slice(0, 4), mo = +r.dateKey.slice(4, 6), d = +r.dateKey.slice(6, 8);
  return Date.UTC(y, mo - 1, d) / 1000 - 9 * 3600 + (r.m - r.lead) * 60;
}
const remKey = (r) => `${r.type || "dep"}|${r.stopId || r.stopName}|${r.m}|${r.h}`;
async function pushSchedule(r) {
  const sub = await ensurePush();
  if (!sub) return;
  const isArr = r.type === "arrive";
  fetch("/api/push/remind", { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({
      subscription: sub.toJSON(), fireAt: reminderEpoch(r), key: remKey(r), tag: `bt${r.m}`,
      title: isArr ? `🎯 Get off: ${r.stopName} ${en(r.stopName)}`
                   : `${r.kind === "train" ? "🚆" : "🚌"} ${r.kind === "train" ? enRoute(r.r) : r.r} ${r.h}`,
      body: isArr ? `Arriving around ${fmtMin(r.m)} — get ready to get off.`
                  : `Leaves ${r.stopName} ${en(r.stopName)} at ${fmtMin(r.m)}.`,
    }) }).catch(() => {});
}
async function pushCancel(r) {
  const sub = await ensurePush();
  if (!sub) return;
  fetch("/api/push/cancel", { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ endpoint: sub.endpoint, key: remKey(r) }) }).catch(() => {});
}
async function notify(title, body, tag) {
  try {
    const reg = await navigator.serviceWorker?.getRegistration();
    if (reg) await reg.showNotification(title, { body, icon: "icon-192.png", tag,
      requireInteraction: true, vibrate: [200, 100, 200] });
    else new Notification(title, { body });
  } catch { /* fall through to toast */ }
  toast(`${title} — ${body}`, 15000);
  beep();
}

async function fireDue() {
  const n = jstNow(), nowMin = n.h * 60 + n.mi, tk = dateKey(n);
  let changed = false;
  for (const r of state.reminders) {
    if (r.fired || r.dateKey !== tk) continue;
    if (nowMin >= r.m - r.lead && nowMin <= r.m) {
      r.fired = true; changed = true;
      const isArr = r.type === "arrive";
      await notify(
        isArr ? `🎯 Get off: ${r.stopName} ${en(r.stopName)}`
              : `${r.kind === "train" ? "🚆" : "🚌"} ${r.r} ${r.h}`,
        isArr ? `Arriving around ${fmtMin(r.m)} — get ready to get off.`
              : `Leaves ${r.stopName} at ${fmtMin(r.m)} — in ${r.m - nowMin} min!`,
        `bt${r.m}`);
    }
    if (r.dateKey < tk) { r.fired = true; changed = true; } // expire stale
  }
  if (changed) { save(); renderReminders(); renderNextReminderBanner(nowMin, tk); ensureGpsWatch(); }
}

/* ---------- GPS get-off watch ---------- */
const GPS_RADIUS = { bus: 400, train: 800 }; // meters — train needs more warning
let gpsWatchId = null;
function activeGpsReminders() {
  const tk = dateKey(jstNow());
  return state.reminders.filter((r) => r.type === "arrive" && !r.fired &&
    r.dateKey === tk && r.lat != null);
}
function ensureGpsWatch() {
  const active = activeGpsReminders();
  if (active.length && gpsWatchId == null && navigator.geolocation) {
    gpsWatchId = navigator.geolocation.watchPosition(onGpsPosition, () => {},
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 });
  } else if (!active.length && gpsWatchId != null) {
    navigator.geolocation.clearWatch(gpsWatchId);
    gpsWatchId = null;
  }
}
async function onGpsPosition(pos) {
  const { latitude: lat, longitude: lon, accuracy } = pos.coords;
  state.geo = { lat, lon };
  let changed = false;
  for (const r of activeGpsReminders()) {
    const dist = haversine(lat, lon, r.lat, r.lon);
    const radius = GPS_RADIUS[r.kind] || 400;
    if (dist <= radius + Math.min(accuracy || 0, 100)) {
      r.fired = true; changed = true;
      await notify(`🎯 Get off NOW: ${r.stopName} ${en(r.stopName)}`,
        `You are ~${fmtDist(dist)} from ${en(r.stopName) || r.stopName} — this is your stop!`,
        `btgps${r.m}`);
    }
  }
  if (changed) { save(); renderReminders(); ensureGpsWatch(); }
}
function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination);
    o.frequency.value = 880; g.gain.value = 0.15;
    o.start(); o.stop(ctx.currentTime + 0.4);
  } catch { /* silent */ }
}

/* ---------- detail sheet ---------- */
async function openDetail(id) {
  state.detailId = id; state.detailDay = null;
  const meta = stopMeta(id), feed = state.index.feeds[meta.feed];
  $("#detail-name").textContent = meta.name;
  $("#detail-sub").textContent =
    `${en(meta.name) ? en(meta.name) + " · " : ""}${feed.name_en}`;
  updateStarBtn();
  $("#detail").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  renderDetail();
}
function updateStarBtn() {
  const on = state.saved.includes(state.detailId);
  const b = $("#detail-star");
  b.textContent = on ? "★" : "☆"; b.classList.toggle("on", on);
}
async function renderDetail() {
  const id = state.detailId;
  const meta = stopMeta(id);
  const stop = await loadStop(id);
  const n = jstNow(), nowMin = n.h * 60 + n.mi, tk = dateKey(n);
  const todayDt = String(dayType(meta.feed, tk));
  const labels = state.index.feeds[meta.feed].dt_labels || {};
  // collapse day types whose departure lists are identical at THIS stop
  const groups = new Map(); // rowsJSON -> [dt,...]
  for (const dt of Object.keys(stop.departures)) {
    const key = JSON.stringify(stop.departures[dt]);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(dt);
  }
  const tabs = [...groups.values()].map((dts) => ({
    dt: dts.includes(todayDt) ? todayDt : dts[0],
    label: (labels[dts.find((d) => !/ [A-Z]$/.test(labels[d] || ""))] || labels[dts[0]] || `Type ${dts[0]}`),
    isToday: dts.includes(todayDt),
  }));
  const active = state.detailDay ?? (tabs.find((t) => t.isToday)?.dt ?? tabs[0]?.dt);
  $("#detail-days").innerHTML = tabs.map((t) =>
    `<button class="${t.dt === active ? "active" : ""}" data-day="${t.dt}">
      ${t.label}${t.isToday ? " · today" : ""}</button>`).join("");
  const rows = (stop.departures[active] || []).map(([m, r, h]) => ({ m: m % 1440, r, h }));
  const isToday = active === String(todayDt);
  $("#detail-list").innerHTML = rows.map((d) =>
    depRow(stop, d, nowMin, { past: isToday && d.m < nowMin })).join("") ||
    `<div class="empty"><p>No departures for this day type.</p></div>`;
  const firstUp = rows.findIndex((d) => !(isToday && d.m < nowMin));
  if (firstUp > 2) $("#detail-list").children[firstUp]?.scrollIntoView({ block: "center" });
}

/* ---------- tabs / events ---------- */
function showTab(t) {
  state.tab = t;
  document.querySelectorAll(".tab").forEach((el) => el.classList.add("hidden"));
  $(`#tab-${t}`).classList.remove("hidden");
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.tab === t));
  refresh();
}
function toast(msg, ms = 2500) {
  const t = $("#toast");
  t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), ms);
}
function refresh() {
  if (state.tab === "search") renderSearch();
  if (state.tab === "compare") renderCompare();
  if (state.tab === "reminders") {
    renderReminders();
    if (typeof renderAccount === "function") { renderAccount(); renderHistory(); }
  }
  if (!$("#detail").classList.contains("hidden")) renderDetail();
}

function bindEvents() {
  document.querySelector("nav").addEventListener("click", (e) => {
    const a = e.target.closest("a[data-tab]");
    if (a) { state.vsPicking = null; showTab(a.dataset.tab); }
  });
  document.body.addEventListener("click", async (e) => {
    const open = e.target.closest("[data-open]");
    const star = e.target.closest("[data-star]");
    const bell = e.target.closest("[data-rem]");
    const del = e.target.closest("[data-del]");
    const day = e.target.closest("[data-day]");
    const pick = e.target.closest("[data-pick]");
    if (star) {
      const id = star.dataset.star;
      const i = state.saved.indexOf(id);
      i >= 0 ? state.saved.splice(i, 1) : state.saved.push(id);
      save(); refresh();
      toast(i >= 0 ? "Removed from Home" : "★ Pinned to Home");
      if (state.detailId === id) updateStarBtn();
    } else if (bell) {
      toggleReminder(JSON.parse(bell.dataset.rem));
    } else if (del) {
      const [removed] = state.reminders.splice(parseInt(del.dataset.del, 10), 1);
      if (removed) pushCancel(removed);
      save(); renderReminders();
      ensureGpsWatch();
    } else if (day) {
      state.detailDay = day.dataset.day; renderDetail();
    } else if (pick) {
      const id = pick.dataset.pick;
      const meta = stopMeta(id);
      let walk = null, dist = "";
      if (state.geo) {
        const m = haversine(state.geo.lat, state.geo.lon, meta.lat, meta.lon);
        walk = walkMin(m); dist = fmtDist(m);
      }
      state.vs[state.vsPicking] = { id, walkMin: walk, dist };
      state.vsPicking = null; save(); showTab("compare");
    } else if (open) {
      openDetail(open.dataset.open);
    }
  });
  $("#detail-close").addEventListener("click", () => {
    $("#detail").classList.add("hidden"); document.body.style.overflow = ""; refresh();
  });
  $("#detail-star").addEventListener("click", () => {
    const id = state.detailId, i = state.saved.indexOf(id);
    i >= 0 ? state.saved.splice(i, 1) : state.saved.push(id);
    save(); updateStarBtn();
  });
  $("#search-input").addEventListener("input", renderSearch);
  document.querySelectorAll(".fbtn").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".fbtn").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); state.searchKind = b.dataset.f; renderSearch();
  }));
  $("#nearby-btn").addEventListener("click", renderNearby);
  $("#vs-locate").addEventListener("click", vsAutoPick);
  $("#vs-pick-bus").addEventListener("click", () => { state.vsPicking = "bus"; showTab("search");
    $("#search-input").value = ""; toast("Pick a bus stop for the comparison"); renderSearch(); });
  $("#vs-pick-train").addEventListener("click", () => { state.vsPicking = "train"; showTab("search");
    $("#search-input").value = ""; toast("Pick a train station for the comparison"); renderSearch(); });
  $("#lead-select").addEventListener("change", (e) => { state.lead = parseInt(e.target.value, 10); save(); });
  $("#notif-enable").addEventListener("click", async () => {
    await Notification.requestPermission();
    await ensurePush(); // register for background delivery too
    updateNotifBanner();
  });
  $("#howto-close").addEventListener("click", () => {
    localStorage.setItem("bt_howto_done", "1");
    $("#ios-howto").classList.add("hidden");
  });
}
const IS_IOS = /iP(hone|ad|od)/.test(navigator.userAgent);
const IS_STANDALONE = window.matchMedia("(display-mode: standalone)").matches ||
  navigator.standalone === true;
function updateNotifBanner() {
  // iPhone in Safari (not installed): show the Add-to-Home-Screen walkthrough
  const showHowto = IS_IOS && !IS_STANDALONE && !localStorage.getItem("bt_howto_done");
  $("#ios-howto").classList.toggle("hidden", !showHowto);

  const perm = "Notification" in window ? Notification.permission : "unsupported";
  let show = false;
  if (perm === "default" && (IS_STANDALONE || state.reminders.some((r) => !r.fired))) {
    show = true;
    $("#notif-msg").textContent =
      "Enable notifications so reminders can reach you — even when the app is closed.";
    $("#notif-enable").classList.remove("hidden");
  } else if (perm === "denied" && state.reminders.some((r) => !r.fired)) {
    show = true;
    $("#notif-msg").textContent = IS_IOS
      ? "Notifications are off. Turn them on in Settings → Notifications → BusTrain."
      : "Notifications are blocked for this site — allow them in your browser settings.";
    $("#notif-enable").classList.add("hidden");
  }
  $("#notif-banner").classList.toggle("hidden", !show);
}

/* ---------- boot ---------- */
async function boot() {
  await loadIndex();
  bindEvents();
  showTab("compare");
  setInterval(() => {
    const n = jstNow();
    $("#clock").textContent = `${String(n.h).padStart(2, "0")}:${String(n.mi).padStart(2, "0")}`;
    fireDue();
  }, 5000);
  setInterval(refresh, 30000); // countdown refresh
  const n = jstNow();
  $("#clock").textContent = `${String(n.h).padStart(2, "0")}:${String(n.mi).padStart(2, "0")}`;
  updateNotifBanner();
  fireDue();
  ensureGpsWatch();
  ensurePush();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js?v=38").catch(() => {});
    // when a new version takes over, reload once so users always run latest
    let reloaded = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (reloaded) return;
      reloaded = true;
      if (navigator.serviceWorker.controller) location.reload();
    });
  }
}
boot();
