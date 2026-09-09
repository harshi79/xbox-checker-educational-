import os
import json
import hashlib
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field
from typing import Optional

from . import db, auth, rate_limit, watermark, checker

app = FastAPI(title="Xbox Checker SaaS", version="1.0.0")

# Mount static files for frontend
app.mount("/static", StaticFiles(directory="static"), name="static")

# ============ Pydantic Models ============
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    device_fingerprint: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class CheckRequest(BaseModel):
    email: str
    password: str
    proxies: Optional[list[str]] = None  # User-provided proxies

class APIResponse(BaseModel):
    status: str
    data: Optional[dict] = None
    duration: Optional[float] = None
    watermark: str
    signature: str

# ============ Helper: Get Current User ============
async def get_current_user(authorization: str = Header(...)) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid authorization header")
    
    api_key = authorization[7:]
    user = await db.fetchone(
        "SELECT id, email, tier, is_active FROM users WHERE api_key = ?",
        api_key
    )
    if not user or not user["is_active"]:
        raise HTTPException(401, "Invalid or revoked API key")
    return user

# ============ Auth Routes ============
@app.post("/auth/register")
async def register(req: RegisterRequest):
    # Check for duplicate fingerprint
    existing = await db.fetchone(
        "SELECT id FROM users WHERE device_fingerprint = ?",
        req.device_fingerprint
    )
    if existing:
        raise HTTPException(400, "Device already registered")
    
    # Check for duplicate email
    if await db.fetchone("SELECT id FROM users WHERE email = ?", req.email):
        raise HTTPException(400, "Email already registered")
    
    # Create user
    api_key = auth.generate_api_key()
    await db.execute("""
        INSERT INTO users (email, password_hash, api_key, tier, device_fingerprint)
        VALUES (?, ?, ?, 'free', ?)
    """, req.email, auth.hash_password(req.password), api_key, req.device_fingerprint)
    
    return {"api_key": api_key, "message": "Registration successful"}

@app.post("/auth/login")
async def login(req: LoginRequest):
    user = await db.fetchone(
        "SELECT id, email, password_hash, api_key, tier FROM users WHERE email = ?",
        req.email
    )
    if not user or not auth.verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    
    token = auth.create_jwt_token({"sub": user["email"], "user_id": user["id"]})
    return {"access_token": token, "token_type": "bearer", "api_key": user["api_key"], "tier": user["tier"]}

@app.get("/user/me")
async def get_profile(user: dict = Depends(get_current_user)):
    usage = await db.fetchone(
        "SELECT count, tier_limit FROM daily_usage WHERE user_id = ? AND check_date = ?",
        user["id"], datetime.now().date().isoformat()
    )
    return {
        "email": user["email"],
        "tier": user["tier"],
        "daily_usage": usage["count"] if usage else 0,
        "daily_limit": usage["tier_limit"] if usage else rate_limit.TIER_LIMITS[user["tier"]]
    }

@app.post("/user/key/revoke")
async def revoke_key(user: dict = Depends(get_current_user)):
    new_key = auth.generate_api_key()
    await db.execute("UPDATE users SET api_key = ? WHERE id = ?", new_key, user["id"])
    return {"api_key": new_key, "message": "API key regenerated"}

# ============ Core Check Endpoint ============
@app.post("/check", response_model=APIResponse)
async def check_account(req: CheckRequest, user: dict = Depends(get_current_user)):
    # Rate limit check
    allowed, remaining = await rate_limit.check_and_increment(user["id"], user["tier"])
    if not allowed:
        raise HTTPException(429, f"Daily limit reached. Resets at midnight UTC. Remaining: {remaining}")
    
    # Run checker
    try:
        result = await checker.check_account_async(req.email, req.password, req.proxies)
    except Exception as e:
        result = {"status": "ERROR", "duration": 0, "error": str(e)}
    
    # Log request
    await db.execute("""
        INSERT INTO request_logs (user_id, proxy_used, status, result_snapshot)
        VALUES (?, ?, ?, ?)
    """, user["id"], json.dumps(req.proxies) if req.proxies else None, 
        result.get("status"), json.dumps(result))
    
    # Add watermark and signature
    signed = watermark.sign_response(result)
    return JSONResponse(content=signed)

# ============ Admin Routes ============
async def require_admin(x_admin_key: str = Header(...)):
    admin_key = os.environ.get("ADMIN_API_KEY")
    if not admin_key or not hmac.compare_digest(x_admin_key, admin_key):
        raise HTTPException(403, "Admin access denied")

@app.get("/admin/users")
async def admin_list_users(admin: None = Depends(require_admin)):
    users = await db.fetchall("""
        SELECT id, email, tier, api_key, created_at, is_active, device_fingerprint 
        FROM users ORDER BY created_at DESC
    """)
    return {"users": users}

@app.patch("/admin/users/{user_id}")
async def admin_update_user(
    user_id: int,
    tier: Optional[str] = None,
    revoke: Optional[bool] = None,
    admin: None = Depends(require_admin)
):
    if tier and tier not in ["free", "premium", "pro"]:
        raise HTTPException(400, "Invalid tier")
    
    if revoke:
        new_key = auth.generate_api_key()
        await db.execute("UPDATE users SET api_key = ? WHERE id = ?", new_key, user_id)
        return {"api_key": new_key}
    
    if tier:
        await db.execute("UPDATE users SET tier = ? WHERE id = ?", tier, user_id)
    
    return {"message": "User updated"}

# ============ Root & Health ============
@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", "r") as f:
        return f.read()

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
