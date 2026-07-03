/* BusTrain — in-app walking guidance to a stop/station.
   Street route from the OSM community foot router (FOSSGIS OSRM); live GPS
   tracking with follow mode; straight-line fallback when the router is
   unreachable. Loads after app.js and shares its globals. */
"use strict";

let gMap = null, gWatch = null, gDest = null, gLine = null, gYou = null,
    gDestMarker = null, gFollow = true, gArrived = false, gRoutePts = null;

/* remaining walk measured ALONG the route, not as the crow flies —
   matters when the path loops around tracks or rivers */
function remainingOnRoute(lat, lon) {
  if (!gRoutePts || gRoutePts.length < 2) return null;
  let best = 0, bestD = Infinity;
  for (let i = 0; i < gRoutePts.length; i++) {
    const d = haversine(lat, lon, gRoutePts[i][0], gRoutePts[i][1]);
    if (d < bestD) { bestD = d; best = i; }
  }
  if (bestD > 80) return null; // off the route — straight line is more honest
  let sum = bestD;
  for (let i = best; i < gRoutePts.length - 1; i++) {
    sum += haversine(gRoutePts[i][0], gRoutePts[i][1], gRoutePts[i + 1][0], gRoutePts[i + 1][1]);
  }
  return sum;
}

async function openGuide(lat, lon, name) {
  gDest = { lat, lon, name };
  gFollow = true; gArrived = false;
  $("#guide").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  $("#guide-name").textContent = `${name} ${en(name) || ""}`.trim();
  $("#guide-sub").textContent = "Finding your position…";

  if (typeof L === "undefined") { $("#guide-sub").textContent = "Map unavailable offline."; return; }
  if (!gMap) {
    gMap = L.map("guide-map", { zoomControl: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(gMap);
    gMap.on("dragstart", () => { gFollow = false; });
  }
  setTimeout(() => gMap.invalidateSize(), 150);

  [gLine, gYou, gDestMarker].forEach((l) => l && gMap.removeLayer(l));
  gLine = gYou = gDestMarker = null;
  gDestMarker = L.marker([lat, lon], { icon: L.divIcon({ className: "pin", html: "🚏",
    iconSize: [26, 26], iconAnchor: [13, 22] }) }).addTo(gMap)
    .bindPopup(`${name} ${en(name) || ""}`);
  gMap.setView([lat, lon], 16);

  const start = state.geo || await getLocation().catch(() => null);
  if (!start) {
    $("#guide-sub").textContent = "Location unavailable — allow location access and retry.";
    return;
  }
  await drawWalkingRoute(start);
  updateGuidePosition(start.lat, start.lon, 0);

  if (gWatch != null) navigator.geolocation.clearWatch(gWatch);
  gWatch = navigator.geolocation.watchPosition((p) => {
    state.geo = { lat: p.coords.latitude, lon: p.coords.longitude };
    updateGuidePosition(p.coords.latitude, p.coords.longitude, p.coords.accuracy || 0);
  }, () => {}, { enableHighAccuracy: true, maximumAge: 3000, timeout: 20000 });
}

async function drawWalkingRoute(s) {
  try {
    const u = `https://routing.openstreetmap.de/routed-foot/route/v1/foot/` +
      `${s.lon},${s.lat};${gDest.lon},${gDest.lat}?overview=full&geometries=geojson`;
    const r = await fetch(u, { signal: AbortSignal.timeout(6000) });
    const j = await r.json();
    const coords = j.routes[0].geometry.coordinates.map((c) => [c[1], c[0]]);
    gRoutePts = coords;
    gLine = L.polyline(coords, { color: "#1a73e8", weight: 5, opacity: 0.85 }).addTo(gMap);
  } catch { // router down/offline: straight line is still orientation
    gRoutePts = null;
    gLine = L.polyline([[s.lat, s.lon], [gDest.lat, gDest.lon]],
      { color: "#1a73e8", weight: 4, dashArray: "4 8" }).addTo(gMap);
  }
  gMap.fitBounds(gLine.getBounds().pad(0.25), { maxZoom: 18 });
}

function updateGuidePosition(lat, lon, acc) {
  if (!gDest) return;
  if (!gYou) {
    gYou = L.circleMarker([lat, lon], { radius: 9, color: "#fff", weight: 3,
      fillColor: "#1a73e8", fillOpacity: 1 }).addTo(gMap);
  } else {
    gYou.setLatLng([lat, lon]);
  }
  const direct = haversine(lat, lon, gDest.lat, gDest.lon);
  const dist = remainingOnRoute(lat, lon) ?? direct;
  if (direct <= 30 + Math.min(acc, 30)) {
    if (!gArrived) { gArrived = true; beep(); }
    $("#guide-sub").textContent = "🎉 You're here — this is your stop!";
  } else {
    gArrived = false;
    $("#guide-sub").textContent =
      `🚶 ${fmtDist(dist)} · ~${walkMin(dist)} min to go — follow the blue line`;
  }
  if (gFollow) gMap.panTo([lat, lon], { animate: true });
}

function closeGuide() {
  if (gWatch != null) { navigator.geolocation.clearWatch(gWatch); gWatch = null; }
  gDest = null;
  $("#guide").classList.add("hidden");
  if ($("#detail").classList.contains("hidden")) document.body.style.overflow = "";
}

function initGuide() {
  $("#guide-close").addEventListener("click", closeGuide);
  $("#guide-follow").addEventListener("click", () => {
    gFollow = true;
    if (gYou) gMap.panTo(gYou.getLatLng(), { animate: true });
  });
  document.body.addEventListener("click", (e) => {
    const g = e.target.closest("[data-guide]");
    if (!g) return;
    // one gesture: a tapped departure row also arms its reminder
    if (g.dataset.autorem) {
      try {
        const pay = JSON.parse(g.dataset.autorem);
        const n = jstNow(), nowMin = n.h * 60 + n.mi;
        if (pay.m > nowMin && ensureReminder(pay)) {
          toast(`🔔 Reminder set for the ${fmtMin(pay.m)} departure — and here's your walk`);
        }
      } catch { /* malformed attr — just guide */ }
    }
    const [lat, lon] = g.dataset.guide.split(",").map(Number);
    openGuide(lat, lon, g.dataset.guideName || "");
  });
  $("#detail-guide").addEventListener("click", () => {
    const meta = state.detailId && stopMeta(state.detailId);
    if (meta) openGuide(meta.lat, meta.lon, meta.name);
  });
}
initGuide();
