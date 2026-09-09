import secrets
import hashlib
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt, JWTError

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def generate_api_key() -> str:
    return f"xbsp_{secrets.token_urlsafe(32)}"

def create_jwt_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, os.environ.get("JWT_SECRET", "fallback"), algorithm=JWT_ALGORITHM)

def decode_jwt_token(token: str):
    try:
        return jwt.decode(token, os.environ.get("JWT_SECRET", "fallback"), algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
