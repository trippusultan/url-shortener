"""
URL Shortening Service — REST API
──────────────────────────────────
Endpoints
─────────
POST   /shorten               Create a new short URL  { "url": "https://..." }
GET    /shorten/{shortCode}   Retrieve the record for a short code
PUT    /shorten/{shortCode}   Update the destination URL
DELETE /shorten/{shortCode}   Delete a short URL
GET    /shorten/{shortCode}/stats  Get access statistics
GET    /docs                  Swagger / ReDoc
──────────────────────────────────
存储层：JSON 文件 + 内存索引（易迁移到 SQLite/Redis）
短码：7 字符熵值的字母数字随机串，预生成池防碰撞
"""
from __future__ import annotations

import json
import os
import random
import re
import string
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl, field_validator

# ── config ─────────────────────────────────────────────────────────────────────
DB_DIR     = Path(os.getenv("DB_DIR", "/home/spoidy/workspace/url-shortener/data"))
STATS_DIR  = DB_DIR / "stats"
DB_DIR.mkdir(parents=True, exist_ok=True)
STATS_DIR.mkdir(parents=True, exist_ok=True)

DB_FILE    = DB_DIR / ".urls.json"
CODE_LEN   = 7                  # short-code length → 62^7 ≈ 3.5 × 10^12
POOL_SIZE  = 1_000            # pre-generated pool per session

app = FastAPI(
    title="URL Shortening API",
    description="Create, retrieve, update, delete, and track short URLs.",
    version="1.0.0",
)

# ── helpers ────────────────────────────────────────────────────────────────────
_ALPHABET = string.ascii_letters + string.digits   # a-zA-Z0-9 → 62 chars
_CODE_RE  = re.compile(r"^[a-zA-Z0-9]{" + str(CODE_LEN) + r"}$")

def _gen_code() -> str:
    return "".join(random.choices(_ALPHABET, k=CODE_LEN))

def _generate_pool(n: int = POOL_SIZE) -> list[str]:
    """Generate a flat list of unique codes and persist them."""
    codes: set[str] = set()
    while len(codes) < n:
        codes.add(_gen_code())
    pool_path = DB_DIR / "_pool.json"
    pool_path.write_text(json.dumps(list(codes)), encoding="utf-8")
    return list(codes)

def _get_or_replenish_pool() -> list[str]:
    pool_path = DB_DIR / "_pool.json"
    if pool_path.exists():
        codes: list[str] = json.loads(pool_path.read_text())
        if len(codes) > 0:
            return codes
    return _generate_pool()

def _pop_code(pool: list[str]) -> str:
    code = pool.pop()
    (DB_DIR / "_pool.json").write_text(json.dumps(pool), encoding="utf-8")
    return code

def _load_db() -> dict[str, dict]:
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text(encoding="utf-8"))
    return {}

def _save_db(db: dict) -> None:
    tmp = str(DB_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, default=str)
    os.replace(tmp, str(DB_FILE))

def _incr_stat(code: str) -> None:
    sf = STATS_DIR / f"{code}.json"
    data: dict[str, Any] = {}
    if sf.exists():
        data = json.loads(sf.read_text(encoding="utf-8"))
    data["accessCount"] = data.get("accessCount", 0) + 1
    data["lastAccess"]  = datetime.now(timezone.utc).isoformat()
    sf.write_text(json.dumps(data, indent=2), encoding="utf-8")

# ── pydantic ────────────────────────────────────────────────────────────────────
class ShortenRequest(BaseModel):
    url: str = Query(..., min_length=3, description="The long URL to shorten")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        # Basic scheme + host check
        if not re.match(r"^https?://", v):
            raise ValueError("URL must start with http:// or https://")
        return v

class UrlRecord(BaseModel):
    id:        str
    url:       str
    shortCode: str
    createdAt: str
    updatedAt: str

# ── core CRUD ──────────────────────────────────────────────────────────────────

def _create_record(url: str) -> UrlRecord:
    if not re.match(r"^https?://", url):
        raise HTTPException(400, detail="URL must start with http:// or https://")

    db = _load_db()

    # Check if exact URL already shortened — return existing code
    for rec in db.values():
        if rec["url"] == url:
            return UrlRecord(**rec)

    pool = _get_or_replenish_pool()
    # Infinite fallback: generate on demand if pool is empty
    if not pool:
        pool = [_gen_code() for _ in range(POOL_SIZE)]
    # Select a random code from the pool, retry on collision (extremely rare with 62^7 space)
    existing = set(db.keys())
    random.shuffle(pool)
    code = next(c for c in pool if c not in existing)
    pool.remove(code)                                   # consume chosen code
    (DB_DIR / "_pool.json").write_text(json.dumps(pool), encoding="utf-8")

    now = datetime.now(timezone.utc).isoformat()
    rec: dict = {
        "id": code,          # use code as id; also stable primary key
        "url": url,
        "shortCode": code,
        "createdAt": now,
        "updatedAt": now,
    }
    db[code] = rec
    _save_db(db)
    return UrlRecord(**rec)

def _get_record(shortCode: str) -> dict:
    db = _load_db()
    if shortCode not in db:
        raise HTTPException(404, detail=f"Short URL '{shortCode}' not found")
    return db[shortCode]

# ── endpoints ──────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False, response_model=dict[str, str])
def root():
    return {
        "service": "URL Shortening API",
        "docs": "/docs",
        "healthz": "/healthz",
    }

@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}

# CREATE
@app.post("/shorten", response_model=UrlRecord, status_code=status.HTTP_201_CREATED,
          summary="Create a short URL")
def shorten(request: ShortenRequest):
    """
    Create a new short URL.
    Body: `{ "url": "https://www.example.com/some/long/path" }`
    If the same URL already exists the existing short code is returned.
    """
    return _create_record(request.url)

# READ (record)
@app.get("/shorten/{shortCode}", response_model=UrlRecord,
         summary="Retrieve short URL record by code")
def get_shorten(shortCode: str):
    """Return the metadata record for the given short code."""
    return _get_record(shortCode)

# READ (stats)
@app.get("/shorten/{shortCode}/stats", summary="Get statistics for a short URL")
def get_stats(shortCode: str) -> dict[str, Any]:
    """Return access count and timestamps for this short URL."""
    record = _get_record(shortCode)
    sf   = STATS_DIR / f"{shortCode}.json"
    stats_data: dict[str, Any] = {}
    if sf.exists():
        stats_data = json.loads(sf.read_text(encoding="utf-8"))
    return {
        **record,
        "accessCount": stats_data.get("accessCount", 0),
        "lastAccess":  stats_data.get("lastAccess", None),
    }

# UPDATE
@app.put("/shorten/{shortCode}", response_model=UrlRecord, summary="Update a short URL")
def update_shorten(shortCode: str, request: ShortenRequest):
    """
    Update the destination URL of an existing short code.
    The `updatedAt` timestamp is refreshed.
    """
    db = _load_db()
    if shortCode not in db:
        raise HTTPException(404, detail=f"Short URL '{shortCode}' not found")
    if not re.match(r"^https?://", request.url):
        raise HTTPException(400, detail="URL must start with http:// or https://")
    db[shortCode]["url"]        = request.url
    db[shortCode]["updatedAt"]  = datetime.now(timezone.utc).isoformat()
    _save_db(db)
    return UrlRecord(**db[shortCode])

# DELETE
@app.delete("/shorten/{shortCode}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete a short URL")
def delete_shorten(shortCode: str):
    db = _load_db()
    if shortCode not in db:
        raise HTTPException(404, detail=f"Short URL '{shortCode}' not found")
    del db[shortCode]
    _save_db(db)
    # Clean up stats file too
    sf = STATS_DIR / f"{shortCode}.json"
    if sf.exists():
        sf.unlink()
    return Response(status_code=204)

# REDIRECT (convenience — shortCode → destination)
@app.get("/r/{shortCode}", summary="Redirect to the original URL")
def redirect_shorten(shortCode: str):
    """Increment access count and redirect the user to the original URL."""
    db = _load_db()
    if shortCode not in db:
        raise HTTPException(404, detail=f"Short URL '{shortCode}' not found")
    _incr_stat(shortCode)
    return RedirectResponse(url=db[shortCode]["url"], status_code=302)

# ── static files ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="/home/spoidy/workspace/url-shortener/static"), name="static")
