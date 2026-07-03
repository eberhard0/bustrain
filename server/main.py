"""BusTrain backend — static site + optional accounts + trip history.

Anonymous users get the full app; nothing is persisted server-side
unless they register/log in. Run: uvicorn main:app --port 3021
"""
import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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


app.mount("/", StaticFiles(directory=WEB, html=True), name="static")
