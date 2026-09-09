import os
from libsql_client import create_client
from contextlib import asynccontextmanager

_client = None

def get_client():
    global _client
    if _client is None:
        _client = create_client(
            url=os.environ["TURSO_DATABASE_URL"],
            auth_token=os.environ.get("TURSO_AUTH_TOKEN", "")
        )
    return _client

@asynccontextmanager
async def get_db_connection():
    client = get_client()
    try:
        yield client
    finally:
        pass  # libsql-client manages connection pooling internally

async def execute(query: str, *args):
    async with get_db_connection() as conn:
        return await conn.execute(query, args)

async def fetchone(query: str, *args):
    async with get_db_connection() as conn:
        result = await conn.execute(query, args)
        return result.rows[0] if result.rows else None

async def fetchall(query: str, *args):
    async with get_db_connection() as conn:
        result = await conn.execute(query, args)
        return result.rows

async def init_db():
    """Run initial migrations on startup"""
    with open("migrations/initial.sql", "r") as f:
        schema = f.read()
    # libsql-client doesn't support multi-statement exec directly
    # Split by semicolon and execute individually
    for stmt in schema.split(";"):
        stmt = stmt.strip()
        if stmt and not stmt.startswith("--"):
            await execute(stmt)
