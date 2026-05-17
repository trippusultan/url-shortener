# URL Shortening Service

A fully-tested REST API for creating, managing, and tracking short URLs — with automatic redirects, editable destinations, and per-link access statistics.

---

## 🚀 Quick Start

```bash
# Install dependencies (Python venv)
pip install -r requirements.txt

# Start the dev server
uvicorn main:app --reload --port 5030

# Hit interactive API docs
open http://localhost:5030/docs
```

---

## 📐 Architecture

```
url-shortener/
├── main.py             — FastAPI app + all endpoints
├── requirements.txt    — Dependencies
├── data/
│   ├── .urls.json      — Primary store: shortCode → record (createdAt, updatedAt, url, id)
│   ├── _pool.json      — Pre-generated pool of random 7-char codes
│   └── stats/          — Per-code files: { shortCode }.json → { accessCount, lastAccess }
```

| Layer | Choice | Why |
|---|---|---|
| Framework | FastAPI | Auto docs, validation, type hints |
| Store | JSON files | Zero-config, easy to swap to SQLite/Redis |
| Short-code | 62-char alphabet pool (a-zA-Z0-9) → 62⁷ ≈ 3.5 × 10¹² combos | Collision probability ≈ 1 in a trillion |
| Stats | Append-free JSON writes | O(1) per redirect, no DB contention |

---

## ✨ Features

| # | Feature | Endpoint |
|---|---|---|
| 1 | Create short URL | `POST /shorten` |
| 2 | Retrieve original URL record | `GET /shorten/{shortCode}` |
| 3 | Update destination URL | `PUT /shorten/{shortCode}` |
| 4 | Delete short URL | `DELETE /shorten/{shortCode}` |
| 5 | Get access statistics | `GET /shorten/{shortCode}/stats` |
| _ | Auto-redirect with click tracking | `GET /r/{shortCode}` _(bonus)_ |
| _ | Health check | `GET /healthz` |

---

## 🔌 API Reference

> Every endpoint is available under the **Swagger / ReDoc** at `http://localhost:5030/docs` — try it live without writing a single `curl` command.

---

### Create Short URL

```http
POST /shorten
Content-Type: application/json

{ "url": "https://www.example.com/some/long/path" }
```

**201 Created** — record with generated `shortCode`:

```json
{
  "id": "7G4xBqR",
  "url": "https://www.example.com/some/long/path",
  "shortCode": "7G4xBqR",
  "createdAt": "2026-05-17T13:38:23.553726+00:00",
  "updatedAt": "2026-05-17T13:38:23.553726+00:00"
}
```

**400 Bad Request** — missing or malformed body:

```json
{ "detail": [{ "type": "value_error", "loc": ["body", "url"], "msg": "Value error, URL must start with http:// or https://"}] }
```

> 💡 If the exact same URL is submitted again, the *existing* `shortCode` is returned instead of creating a duplicate.

---

### Get Original URL Record

```http
GET /shorten/{shortCode}
```

**200 OK**:

```json
{
  "id": "7G4xBqR",
  "url": "https://www.example.com/some/long/path",
  "shortCode": "7G4xBqR",
  "createdAt": "2026-05-17T13:38:23.553726+00:00",
  "updatedAt": "2026-05-17T13:38:23.553726+00:00"
}
```

**404 Not Found**:

```json
{ "detail": "Short URL 'INVALID' not found" }
```

---

### Update Short URL

```http
PUT /shorten/{shortCode}
Content-Type: application/json

{ "url": "https://www.example.com/some/updated/path" }
```

**200 OK** — `updatedAt` is refreshed:

```json
{
  "id": "7G4xBqR",
  "url": "https://www.example.com/some/updated/path",
  "shortCode": "7G4xBqR",
  "createdAt": "2026-05-17T13:38:23.553726+00:00",
  "updatedAt": "2026-05-17T13:39:01.200000+00:00"
}
```

**404 Not Found** — non-existent `shortCode`:

```json
{ "detail": "Short URL 'xyz1234' not found" }
```

---

### Delete Short URL

```http
DELETE /shorten/{shortCode}
```

**204 No Content** — no body returned.

**404 Not Found**:

```json
{ "detail": "Short URL 'xyz1234' not found" }
```

---

### Get Statistics

```http
GET /shorten/{shortCode}/stats
```

**200 OK**:

```json
{
  "id": "7G4xBqR",
  "url": "https://www.example.com/some/long/path",
  "shortCode": "7G4xBqR",
  "createdAt": "2026-05-17T13:38:23.553726+00:00",
  "updatedAt": "2026-05-17T13:38:23.553726+00:00",
  "accessCount": 42,
  "lastAccess": "2026-05-17T14:01:00.123456+00:00"
}
```

| Field | Description |
|---|---|
| `accessCount` | Total number of requests to `/r/{shortCode}` |
| `lastAccess` | ISO 8601 timestamp of the most recent redirect (null = never used) |

---

### Redirect (Bonus)

```http
GET /r/{shortCode}
```

Increments `accessCount` by 1 and returns **302 Found** with a `Location` header pointing at the destination URL. Use this for real-world usage in production.

---

## 🧪 Testing

All 9 test scenarios below pass ✅ using `curl` (no external test framework required):

```bash
# 1. create
curl -X POST http://localhost:5030/shorten \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.example.com/some/long/url"}'

# 2. read
curl http://localhost:5030/shorten/<shortCode>

# 3. update
curl -X PUT http://localhost:5030/shorten/<shortCode> \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.example.com/updated"}'

# 4. stats
curl http://localhost:5030/shorten/<shortCode>/stats

# 5. redirect
curl http://localhost:5030/r/<shortCode> -v

# 6. delete
curl -X DELETE http://localhost:5030/shorten/<shortCode> -v

# 7. 404 after delete
curl http://localhost:5030/shorten/<shortCode>

# 8. duplicate-submit — same URL returns existing code
curl -X POST http://localhost:5030/shorten \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.example.com/some/long/url"}'

# 9. invalid URL scheme
curl -X POST http://localhost:5030/shorten \
  -H "Content-Type: application/json" \
  -d '{"url":"ftp://example.com"}'
```

---

## 📋 Validation Rules

| Rule | Error |
|---|---|
| `url` field is required | `422: Field required` |
| Must start with `http://` or `https://` | `422: URL must start with http:// or https://` |
| Minimum 3 characters | `422: String should have at least 3 characters` |
| Duplicate URLs return existing code | `201` with existing `shortCode` |

---

## 🔑 Short Code Generation

- **Length:** 7 characters  
- **Alphabet:** `[a-zA-Z0-9]` — 62 possible values per position  
- **Entropy:** 62⁷ ≈ **3.5 × 10¹²** combinations → ~22 bits of collision-free space per code  
- **Pool strategy:** A pre-generated pool of 1,000 codes is shuffled and stored in `data/_pool.json`. A code is picked at random, removed from the pool, and written back — ensuring near-O(1) code generation with zero blocking.  

---

## 📊 Data Model

### `data/.urls.json`

```json
{
  "7G4xBqR": {
    "id": "7G4xBqR",
    "url": "https://www.example.com/some/long/path",
    "shortCode": "7G4xBqR",
    "createdAt": "2026-05-17T13:38:23.553726+00:00",
    "updatedAt": "2026-05-17T13:38:23.553726+00:00"
  }
}
```

### `data/stats/{shortCode}.json`

```json
{ "accessCount": 42, "lastAccess": "2026-05-17T14:01:00.123456+00:00" }
```

---

## 🛠️ Tech Stack

| Tool | Version |
|---|---|
| Python | 3.11 |
| FastAPI | 0.136+ |
| Uvicorn | 0.47+ (with `httptools` + `uvloop`) |
| httpx | 0.28+ |
| python-multipart | 0.0.28 |

---

## 📦 Dependencies

```
fastapi>=0.100.0
uvicorn[standard]>=0.30.0
python-multipart>=0.0.6
httpx>=0.24.0
```

---

## 🎓 Learning Objectives

| Concept | How it's implemented |
|---|---|
| RESTful API design | 4 CRUD endpoints + stats, per HTTP verb convention |
| Code generation | Pool-based random string + collision avoidance |
| File-based persistence | Atomic `tmp → rename` to prevent race conditions |
| Pydantic validation | `ShortenRequest` with `field_validator` for URL scheme |
| Status-code semantics | `201`, `200`, `204`, `404`, `422` throughout |
| Access tracking | Separate stats file — zero reads on hot redirect path |
| Redirect response | `RedirectResponse` from FastAPI — 302 with proper `Location` |

---

<div align="center">

**MIT License** · Built with [FastAPI](https://fastapi.tiangolo.com/) · [roadmap.sh](https://roadmap.sh/projects/url-shortening-service)

</div>
