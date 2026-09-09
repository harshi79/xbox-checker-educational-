# 🎮 Xbox Checker — Educational Full-Stack Project

## 📚 Project Overview

**Xbox Checker** is an educational full-stack SaaS application that teaches modern web development concepts by checking Xbox Live account subscriptions. It's built with:

- **FastAPI** — modern Python web framework
- **SQLite / Turso** — database integration (local + cloud)
- **OAuth 2.0** — Microsoft authentication flow
- **HMAC cryptography** — response signing and verification
- **Full-stack architecture** — frontend + backend integration

> ⚠️ **Educational Use Only**: This project is designed for learning purposes. Only check accounts you own or are explicitly authorised to test. All operations are logged for educational demonstration.

---

## 🏗️ Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        EDUCATIONAL LAYERS                       │
├─────────────────────────────────────────────────────────────────┤
│  🌐 FRONTEND (static/index.html)                                 │
│  • Single-page application                                       │
│  • DOM manipulation, event handling                               │
│  • Client-side validation                                        │
│  • HMAC signature verification (educational demo)                │
│  • Accessibility (a11y) features                                  │
├─────────────────────────────────────────────────────────────────┤
│  🔧 BACKEND (api/index.py - FastAPI)                             │
│  • RESTful API endpoints                                          │
│  • Dependency injection                                           │
│  • Authentication (API keys, JWT)                                 │
│  • Rate limiting per tier                                         │
│  • Watermarking + HMAC signing                                    │
├─────────────────────────────────────────────────────────────────┤
│  🔐 SERVICES (api/)                                               │
│  • auth.py — password hashing, API keys, JWT tokens               │
│  • db.py — Turso + SQLite integration                             │
│  • checker.py — Xbox Live API integration                         │
│  • rate_limit.py — daily quotas per user tier                     │
│  • watermark.py — HMAC-SHA256 signing                             │
├─────────────────────────────────────────────────────────────────┤
│  📊 EXTERNAL SERVICES                                              │
│  • Microsoft login (live.com)                                     │
│  • Xbox Live API (xboxlive.com)                                   │
│  • Minecraft services                                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Setup & Installation

### Prerequisites

- Python 3.11+
- Node.js (for frontend tests only)

### 1. Create a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

**Key Packages & What They Teach:**

| Package | Educational Focus |
|---------|-------------------|
| `fastapi` | Modern Python web framework, async, type hints |
| `uvicorn` | ASGI server, production deployment |
| `pydantic` | Data validation, type enforcement, API schemas |
| `passlib[bcrypt]` | Password hashing, security best practices |
| `python-jose` | JWT creation and verification |
| `email-validator` | Email validation, input sanitization |
| `libsql-client` | Turso cloud database integration |
| `httpx` | Async HTTP client, external API calls |

### 3. Environment Configuration

```bash
cp .env.example .env
```

**Key Environment Variables (Educational Focus):**

| Variable | Purpose | Learning Concept |
|----------|---------|------------------|
| `TURSO_DATABASE_URL` | Cloud database connection | Serverless databases, distributed data |
| `TURSO_AUTH_TOKEN` | Authentication for cloud DB | Secrets management |
| `ADMIN_API_KEY` | Admin endpoint protection | API security, header auth |
| `WATERMARK_SECRET` | Response HMAC signing | Cryptography, message integrity |
| `JWT_SECRET` | Dashboard session tokens | Secure tokens, stateless auth |
| `FREE_DAILY_LIMIT` | Rate limiting configuration | Quotas, per-user tracking |

### 4. Run Locally

```bash
uvicorn api.index:app --reload
```

Open http://localhost:8000 — the console, API and docs (`/docs`) are served from the same app.

**Available API Docs**: http://localhost:8000/docs (Auto-generated from Pydantic models)

---

## 🎓 Educational Concepts Covered

### 1. **FastAPI & Python Type Hints**

```python
# models.py style - automatic documentation & validation
class RegisterRequest(BaseModel):
    email: EmailStr          # Built-in email validation
    password: str = Field(..., min_length=8)  # Constrained string
    device_fingerprint: str = Field(..., min_length=4)
```

**Learning Points:**
- Type hints enable automatic API docs (`/docs`)
- Pydantic validates input before it reaches your code
- `Field()` constraints enforce business rules

### 2. **Database Integration (SQLite + Turso)**

```python
# api/db.py - supports both backends
def backend_name() -> str:
    return "turso" if os.environ.get("TURSO_DATABASE_URL") else "sqlite"
```

**Learning Points:**
- Code that works with both local and cloud databases
- Serverless considerations (ephemeral filesystem)
- Connection pooling and thread safety
- Migration system with `migrations/initial.sql`

### 3. **OAuth 2.0 & Microsoft Authentication**

The `checker.py` module demonstrates the Xbox Live auth flow:

1. **Login**: Redirect to Microsoft login page
2. **Token exchange**: PPFT-based credential submission
3. **Xbox Auth**: RPS ticket → XBL token → XSTS token
4. **Profile**: Gamertag, gamerscore detection
5. **Subscriptions**: Xbox Game Pass detection

**Learning Points:**
- OAuth 2.0 authorization code flow
- JSON API consumption
- Token-based authentication
- Third-party API integration

### 4. **HMAC-SHA256 Cryptography**

```python
# api/watermark.py - response signing
def sign_response(payload: dict) -> dict:
    message = json.dumps(signable, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(_secret(), message, hashlib.sha256).hexdigest()
    return {**signable, "signature": signature}
```

**Learning Points:**
- Hash-based Message Authentication Code
- Canonical JSON serialization (sorted keys)
- Integrity verification (client-side verification)
- Preventing tampering

### 5. **Password Hashing & Security**

```python
# api/auth.py - multiple hashing schemes
def hash_password(password: str) -> str:
    if _pwd_context is not None:  # passlib + bcrypt
        return _pwd_context.hash(password)
    return _pbkdf2_hash(password)  # Fallback PBKDF2
```

**Learning Points:**
- bcrypt vs PBKDF2 password hashing
- Self-describing hashes (prefix indicates scheme)
- Fallback strategies for different environments
- Password verification workflow

### 6. **API Design Best Practices**

| Pattern | Implementation | Educational Goal |
|---------|---------------|------------------|
| Bearer token auth | `Authorization: Bearer <api_key>` | HTTP authentication standards |
| Rate limiting | Per-user, per-tier quotas | Throttling, DoS prevention |
| Versioned responses | `APP_VERSION = "1.1.0"` | API versioning |
| Error handling | Custom exceptions, no stack traces | Secure error responses |
| Dependency injection | `Depends(get_current_user)` | FastAPI best practices |

### 7. **Full-Stack Integration**

The project demonstrates end-to-end flow:

```
User interacts → Frontend (JavaScript) → FastAPI backend → Microsoft APIs → Response → Frontend renders
```

**Learning Points:**
- JSON serialization/deserialization
- Bearer token transmission
- HMAC signature verification on client
- Error handling across the stack
- Accessibility and responsive design

---

## 🧪 Testing Suites

### Backend Tests (100% Python)

```bash
python3 qa-backend.test.py
```

**Tests 34 scenarios including:**
- Registration with duplicate detection
- Login with password verification
- Rate limiting and key rotation
- Admin user management
- Check endpoint with stubbed Xbox network
- Input validation

### Frontend Tests (JavaScript + Node)

```bash
# Start mock server
node qa-mock-preview.mjs &

# Run test suites
node qa-live.test.js      # 41 assertions
node qa-frontend.test.js  # 119 assertions
```

**Tests cover:**
- Page load and fingerprint generation
- Registration and login flows
- Error handling (401, 429, 500)
- Signature verification
- XSS protection
- Accessibility features
- Proxy input normalization

---

## 📁 Project Structure (Educational Tour)

```
xbox-checker-educational/
├── api/                          # Backend Python modules
│   ├── __init__.py
│   ├── index.py          # FastAPI app + all routes
│   ├── auth.py           # Passwords, API keys, JWT
│   ├── db.py             # Turso + SQLite database
│   ├── checker.py        # Xbox Live API integration
│   ├── rate_limit.py     # Daily quotas per tier
│   └── watermark.py      # HMAC signing
├── static/                     # Frontend (single HTML file)
│   └── index.html        # Console + API integration
├── migrations/               # Database schema (SQL)
│   └── initial.sql
├── qa/                       # Test suites
│   ├── qa-backend.test.py
│   ├── qa-frontend.test.js
│   ├── qa-live.test.js
│   └── qa-mock-preview.mjs
├── requirements.txt          # Python dependencies
├── vercel.json             # Vercel deployment config
├── .env.example            # Environment variables template
└── README.md               # This documentation
```

**Learning Each Folder:**
- `api/` - Server-side logic, each file has a single responsibility
- `static/` - Client-side code, no build step required
- `migrations/` - SQL schema, database evolution
- `qa/` - Automated testing, quality assurance

---

## 🚀 Deployment Educational Guide

### Local Development (Recommended for Learning)

```bash
# 1. Set up environment
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# 2. Run with SQLite (no config needed - works out of the box)
uvicorn api.index:app --reload

# 3. Access the console at http://localhost:8000
# 4. Check API docs at http://localhost:8000/docs
# 5. Health check at http://localhost:8000/health
```

### Vercel Deployment (Serverless)

```bash
# 1. Create Turso database (for persistent data)
curl -sSfL https://get.tur.so/install.sh | bash
turbo auth login
turbo db create xbox-checker
turbo db show xbox-checker --url
turbo db tokens create xbox-checker

# 2. Deploy
vercel --prod

# 3. Set environment variables in Vercel Dashboard:
#    TURSO_DATABASE_URL, TURSO_AUTH_TOKEN, ADMIN_API_KEY, WATERMARK_SECRET, etc.

# 4. Verify deployment
vercel logs <project-url>
curl https://<project>.vercel.app/health
```

**Educational Comparison: SQLite vs Turso**
- **SQLite**: Local file, ephemeral on Vercel (data lost between invocations) - great for learning
- **Turso**: Cloud SQL, persistent data - production reality

---

## ⚠️ Responsible Use & Safety

This project teaches integration with Microsoft/Xbox APIs. Please observe:

1. **Only test accounts you own** - Never check third-party accounts without permission
2. **Rate limiting** - The app has per-user quotas; don't exceed them educational or not
3. **Credential security** - API keys and secrets are stored; never hardcode them in real apps
4. **API terms of service** - Microsoft's terms restrict automated access; this is a demo
5. **Legal compliance** - Credential stuffing and unauthorized checking is illegal in most jurisdictions

The project includes logging (`request_logs` table) to demonstrate accountability and auditing - educational concepts applicable to real-world systems.

---

## 🔧 Extending the Project

### Learning Opportunities:

1. **Add new subscription types** - Extend `SUB_TYPES` in `checker.py`
2. **Multi-tenant architecture** - Add organization/sub-organization support
3. **Webhook system** - Notify when accounts change status
4. **Metrics dashboard** - Prometheus/Grafana integration
5. **Multi-factor authentication** - Add 2FA flow education
6. **Database indexing** - Experiment with different index strategies
7. **Caching layer** - Add Redis for rate limit tracking
8. **OpenAPI extensions** - Custom documentation, examples

### Educational Extension Ideas:

- Add a "learning mode" that shows the HMAC computation steps
- Create a "security audit" endpoint that explains headers
- Build a separate educational frontend from scratch
- Add unit tests for each module
- Create a deployment checklist document

---

## 📜 License

See [LICENSE](LICENSE) - this is an educational open-source project.

---

## 🙏 Acknowledgments

- Microsoft Xbox Live APIs (for educational demo purposes)
- FastAPI team for the excellent framework
- Vercel for serverless deployment platform
- Turso for cloud SQLite services
- All educational open-source contributors

---

**Happy coding! This project is designed to be learned from, modified, and built upon.** 🎓

---

*Last updated: 2026-09-09*  
*Educational project for learning full-stack web development*