"""BusTrain backend — static site + optional accounts + trip history.

Anonymous users get the full app; nothing is persisted server-side
unless they register/log in. Run: uvicorn main:app --port 3021
"""
import asyncio
import hashlib
import json
import re
import secrets
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from pywebpush import webpush, WebPushException
    PUSH_OK = True
except ImportError:  # push is optional — app still works without it
    PUSH_OK = False

ROOT = Path(__file__).resolve().parent
WEB = ROOT.parent / "web"
DB = ROOT / "bustrain.db"

app = FastAPI(title="BusTrain API", docs_url=None, redoc_url=None)


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    """Keep Cloudflare's edge and browsers honest: revalidate app code,
    cache immutable-ish data briefly."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/data/stops/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    elif path.endswith((".png", ".svg")):
        response.headers["Cache-Control"] = "public, max-age=604800"
    elif path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    else:  # html, js, css, sw, manifest, index/corridors/names data
        response.headers["Cache-Control"] = "no-cache"
    return response


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE,
          salt BLOB NOT NULL, pw_hash BLOB NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(
          token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS history(
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          ts REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS push_subs(
          id INTEGER PRIMARY KEY, endpoint TEXT UNIQUE NOT NULL,
          sub_json TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS push_reminders(
          id INTEGER PRIMARY KEY, sub_id INTEGER NOT NULL REFERENCES push_subs(id) ON DELETE CASCADE,
          fire_at REAL NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
          tag TEXT NOT NULL, client_key TEXT NOT NULL, sent INTEGER DEFAULT 0);
        CREATE INDEX IF NOT EXISTS idx_pr_due ON push_reminders(sent, fire_at);
        """)


init_db()

SESSION_TTL = 90 * 24 * 3600


def hash_pw(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)


def current_user(request: Request):
    token = request.cookies.get("bt_session")
    if not token:
        return None
    with db() as c:
        row = c.execute(
            "SELECT u.id, u.username, s.created FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token=?", (token,)).fetchone()
    if not row or time.time() - row["created"] > SESSION_TTL:
        return None
    return {"id": row["id"], "username": row["username"]}


def set_session(resp: Response, user_id: int):
    token = secrets.token_urlsafe(32)
    with db() as c:
        c.execute("INSERT INTO sessions(token, user_id, created) VALUES(?,?,?)",
                  (token, user_id, time.time()))
    resp.set_cookie("bt_session", token, max_age=SESSION_TTL, httponly=True,
                    samesite="lax", secure=True, path="/")


class Credentials(BaseModel):
    username: str = Field(min_length=2, max_length=40, pattern=r"^[\w.\-@]+$")
    password: str = Field(min_length=6, max_length=200)


class HistoryItem(BaseModel):
    kind: str = Field(pattern=r"^(trip|reminder|compare)$")
    data: dict


@app.post("/api/register")
def register(creds: Credentials, response: Response):
    salt = secrets.token_bytes(16)
    try:
        with db() as c:
            cur = c.execute("INSERT INTO users(username, salt, pw_hash, created) VALUES(?,?,?,?)",
                            (creds.username, salt, hash_pw(creds.password, salt), time.time()))
            uid = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(409, "That username is taken.")
    set_session(response, uid)
    return {"username": creds.username}


@app.post("/api/login")
def login(creds: Credentials, response: Response):
    with db() as c:
        row = c.execute("SELECT id, salt, pw_hash FROM users WHERE username=?",
                        (creds.username,)).fetchone()
    if not row or not secrets.compare_digest(hash_pw(creds.password, row["salt"]), row["pw_hash"]):
        raise HTTPException(401, "Wrong username or password.")
    set_session(response, row["id"])
    return {"username": creds.username}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("bt_session")
    if token:
        with db() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (token,))
    response.delete_cookie("bt_session", path="/")
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    return {"user": current_user(request)}


@app.get("/api/history")
def get_history(request: Request):
    user = current_user(request)
    if not user:
        return {"items": None}  # anonymous: nothing stored
    with db() as c:
        rows = c.execute("SELECT id, ts, kind, data FROM history WHERE user_id=? "
                         "ORDER BY ts DESC LIMIT 300", (user["id"],)).fetchall()
    return {"items": [{"id": r["id"], "ts": r["ts"], "kind": r["kind"],
                       "data": json.loads(r["data"])} for r in rows]}


@app.post("/api/history")
def add_history(item: HistoryItem, request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Log in to save your trips.")
    with db() as c:
        cur = c.execute("INSERT INTO history(user_id, ts, kind, data) VALUES(?,?,?,?)",
                        (user["id"], time.time(), item.kind, json.dumps(item.data, ensure_ascii=False)))
    return {"id": cur.lastrowid}


@app.delete("/api/history/{item_id}")
def delete_history(item_id: int, request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Not logged in.")
    with db() as c:
        c.execute("DELETE FROM history WHERE id=? AND user_id=?", (item_id, user["id"]))
    return {"ok": True}


### Google Maps share-link resolver: "paste the link a friend sent you".
### Follows goo.gl redirects (allowlisted Google hosts only) and extracts
### the place name + coordinates from the final Maps URL.
_GHOSTS = re.compile(r"(^|\.)(google\.[a-z.]{2,6}|goo\.gl|maps\.app\.goo\.gl|app\.goo\.gl)$")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _parse_maps_url(u: str):
    dec = urllib.parse.unquote(u)
    name = None
    m = re.search(r"/maps/place/([^/@?]+)", dec)
    if m:
        name = m.group(1).replace("+", " ").strip()
    for pat in (r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)",   # precise place pin
                r"[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)",
                r"@(-?\d+\.\d+),(-?\d+\.\d+)"):       # map viewport (last resort)
        m = re.search(pat, dec)
        if m:
            return name, float(m.group(1)), float(m.group(2))
    return name, None, None


@app.get("/api/resolve")
def resolve_link(url: str):
    opener = urllib.request.build_opener(_NoRedirect())
    for _ in range(6):
        pu = urllib.parse.urlparse(url)
        if pu.scheme != "https" or not _GHOSTS.search(pu.hostname or ""):
            raise HTTPException(400, "Only Google Maps links are supported.")
        name, lat, lon = _parse_maps_url(url)
        if lat is not None:
            return {"name": name, "lat": lat, "lon": lon}
        # consent pages tuck the real target into ?continue=
        qs = urllib.parse.parse_qs(pu.query)
        if "continue" in qs:
            url = qs["continue"][0]
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = opener.open(req, timeout=10)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                continue
            raise HTTPException(422, "Couldn't follow that link.")
        break
    name, lat, lon = _parse_maps_url(url)
    if lat is None:
        raise HTTPException(422, "No location found in that link — open it in Google Maps "
                                 "and share the place again.")
    return {"name": name, "lat": lat, "lon": lon}


### Web Push — lets get-off/departure reminders reach an installed PWA
### even when it's closed (iOS 16.4+ Home Screen apps, Android, desktop).
VAPID_PRIV = ROOT / "vapid_private.pem"
VAPID_PUB = (ROOT / "vapid_public.txt").read_text().strip() \
    if (ROOT / "vapid_public.txt").exists() else ""
VAPID_CLAIMS = {"sub": "mailto:ebert.ojong@gmail.com"}


class PushSub(BaseModel):
    subscription: dict


class PushRemind(BaseModel):
    subscription: dict
    fireAt: float          # epoch seconds UTC
    title: str = Field(max_length=120)
    body: str = Field(max_length=300)
    tag: str = Field(max_length=64)
    key: str = Field(max_length=128)


class PushCancel(BaseModel):
    endpoint: str
    key: str = Field(max_length=128)


def _sub_id(c, subscription: dict) -> int:
    ep = subscription.get("endpoint", "")
    if not ep.startswith("https://"):
        raise HTTPException(400, "Bad subscription.")
    row = c.execute("SELECT id FROM push_subs WHERE endpoint=?", (ep,)).fetchone()
    if row:
        c.execute("UPDATE push_subs SET sub_json=? WHERE id=?",
                  (json.dumps(subscription), row["id"]))
        return row["id"]
    return c.execute("INSERT INTO push_subs(endpoint, sub_json, created) VALUES(?,?,?)",
                     (ep, json.dumps(subscription), time.time())).lastrowid


@app.get("/api/push/key")
def push_key():
    return {"key": VAPID_PUB, "enabled": PUSH_OK and bool(VAPID_PUB)}


@app.post("/api/push/remind")
def push_remind(req: PushRemind):
    if not (PUSH_OK and VAPID_PUB):
        raise HTTPException(503, "Push not configured on this server.")
    if not time.time() - 60 <= req.fireAt <= time.time() + 48 * 3600:
        raise HTTPException(400, "Reminder time must be within the next 48 h.")
    with db() as c:
        sid = _sub_id(c, req.subscription)
        n = c.execute("SELECT COUNT(*) FROM push_reminders WHERE sub_id=? AND sent=0",
                      (sid,)).fetchone()[0]
        if n >= 50:
            raise HTTPException(429, "Too many pending reminders.")
        c.execute("DELETE FROM push_reminders WHERE sub_id=? AND client_key=? AND sent=0",
                  (sid, req.key))
        c.execute("INSERT INTO push_reminders(sub_id, fire_at, title, body, tag, client_key) "
                  "VALUES(?,?,?,?,?,?)",
                  (sid, req.fireAt, req.title, req.body, req.tag, req.key))
    return {"ok": True}


@app.post("/api/push/cancel")
def push_cancel(req: PushCancel):
    with db() as c:
        c.execute("DELETE FROM push_reminders WHERE sent=0 AND client_key=? AND sub_id IN "
                  "(SELECT id FROM push_subs WHERE endpoint=?)", (req.key, req.endpoint))
    return {"ok": True}


def _deliver_due():
    with db() as c:
        due = c.execute(
            "SELECT r.id, r.title, r.body, r.tag, s.sub_json, s.id AS sid "
            "FROM push_reminders r JOIN push_subs s ON s.id=r.sub_id "
            "WHERE r.sent=0 AND r.fire_at<=? LIMIT 20", (time.time(),)).fetchall()
    for r in due:
        try:
            webpush(json.loads(r["sub_json"]),
                    json.dumps({"title": r["title"], "body": r["body"], "tag": r["tag"]}),
                    vapid_private_key=str(VAPID_PRIV), vapid_claims=dict(VAPID_CLAIMS),
                    ttl=600)
        except WebPushException as e:
            code = getattr(e.response, "status_code", 0)
            if code in (404, 410):  # subscription is gone — drop it
                with db() as c:
                    c.execute("DELETE FROM push_subs WHERE id=?", (r["sid"],))
                continue
        except Exception:
            pass  # transient — row stays unsent only if we continue before marking
        with db() as c:
            c.execute("UPDATE push_reminders SET sent=1 WHERE id=?", (r["id"],))
    # housekeeping: drop delivered rows older than a day
    with db() as c:
        c.execute("DELETE FROM push_reminders WHERE sent=1 AND fire_at<?", (time.time() - 86400,))


@app.on_event("startup")
async def _push_loop():
    if not (PUSH_OK and VAPID_PUB):
        return

    async def loop():
        while True:
            try:
                await asyncio.to_thread(_deliver_due)
            except Exception:
                pass
            await asyncio.sleep(15)
    asyncio.create_task(loop())


app.mount("/", StaticFiles(directory=WEB, html=True), name="static")
