"""Database layer: Turso (libsql) with a local SQLite fallback.

- If ``TURSO_DATABASE_URL`` is set, all queries go to Turso via ``libsql-client``.
- Otherwise a local SQLite database is used so the app boots and works
  anywhere (local dev, preview deploys). On Vercel the filesystem is
  ephemeral, so set Turso env vars for persistent production storage —
  ``/health`` reports which backend is active.

Every ``fetch*`` helper returns plain ``dict`` rows (``fetchall`` returns a
list of dicts) regardless of backend, so callers never depend on driver
row types.
"""

import inspect
import logging
import os
import sqlite3
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = BASE_DIR / "migrations" / "initial.sql"


class DatabaseNotConfigured(RuntimeError):
    """Raised when no database backend can be initialised."""


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def backend_name() -> str:
    """Return 'turso' when Turso is configured, else 'sqlite'."""
    return "turso" if os.environ.get("TURSO_DATABASE_URL") else "sqlite"


def using_turso() -> bool:
    return backend_name() == "turso"


def is_persistent() -> bool:
    """Whether the selected backend is expected to survive a process restart."""
    serverless = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
    if using_turso():
        # libsql-client also accepts file: URLs for adapter QA/local use. That
        # is still ephemeral on a serverless filesystem and must not masquerade
        # as a remote persistent Turso database.
        url = os.environ.get("TURSO_DATABASE_URL", "").strip().lower()
        return not (serverless and url.startswith("file:"))
    # SQLite is durable for local development, but Vercel/AWS writable storage
    # lives in /tmp and is explicitly ephemeral between function instances.
    return not serverless


def configuration_warning() -> str | None:
    """Return an operator-facing database warning without leaking secrets."""
    if using_turso() and not os.environ.get("TURSO_AUTH_TOKEN"):
        url = os.environ.get("TURSO_DATABASE_URL", "")
        if not url.startswith("file:"):
            return "TURSO_DATABASE_URL is set but TURSO_AUTH_TOKEN is missing"
    if not is_persistent():
        return "File-backed storage on this serverless runtime is ephemeral; configure remote Turso for persistent users"
    return None


# ---------------------------------------------------------------------------
# Turso (libsql-client)
# ---------------------------------------------------------------------------

_turso_client = None


def _get_turso_client():
    """Lazily create (and cache) the Turso client.

    ``libsql-client`` versions differ slightly in whether ``create_client``
    is sync or async — handle both.
    """
    global _turso_client
    if _turso_client is not None:
        return _turso_client

    url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    if not url:
        raise DatabaseNotConfigured(
            "TURSO_DATABASE_URL is not set and SQLite fallback is disabled."
        )

    try:
        from libsql_client import create_client
    except ImportError as exc:  # pragma: no cover - packaging issue
        raise DatabaseNotConfigured(
            "Turso is configured but the 'libsql-client' package is not installed."
        ) from exc

    client = create_client(url=url, auth_token=token)
    # Some versions return an awaitable; resolve it if we can.
    if inspect.isawaitable(client):  # pragma: no cover - version dependent
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            client = asyncio.run(client)
        else:
            # We are inside a running loop; stash the awaitable and resolve
            # it on first use (see _resolve_client).
            _turso_client = client
            return _turso_client
    _turso_client = client
    return _turso_client


async def _resolve_client():
    client = _get_turso_client()
    global _turso_client
    if inspect.isawaitable(client):
        client = await client
        _turso_client = client
    return client


def _result_to_dicts(result) -> list[dict]:
    """Normalise a libSQL result set to plain dictionaries.

    ``libsql-client==0.3.x`` returns ``libsql_client.result.Row`` objects.
    Those rows implement ``Sequence`` and expose ``asdict()``, but they are
    deliberately *not* ``list`` or ``tuple`` instances.  Restricting the
    conversion to list/tuple silently produced ``{"value": Row(...)}`` and
    broke every named lookup in production (login, profile and admin).  Keep
    this adapter tolerant of both the current SDK and older/mock result types.
    """
    columns = list(getattr(result, "columns", []) or [])
    rows = list(getattr(result, "rows", []) or [])
    output: list[dict] = []

    for row in rows:
        if isinstance(row, Mapping):
            output.append(dict(row))
            continue

        asdict = getattr(row, "asdict", None)
        if callable(asdict):
            mapped = asdict()
            if isinstance(mapped, Mapping):
                output.append(dict(mapped))
                continue

        # SDK Row is a non-string Sequence.  Some test doubles only implement
        # iteration, so fall back to list(row) when possible.
        values = None
        if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
            values = list(row)
        else:
            try:
                values = list(row)
            except (TypeError, ValueError):
                pass

        if values is not None and columns and len(columns) == len(values):
            output.append(dict(zip(columns, values)))
        elif values is not None:
            output.append({str(i): value for i, value in enumerate(values)})
        else:
            output.append({"value": row})

    return output


# ---------------------------------------------------------------------------
# SQLite fallback (local file)
# ---------------------------------------------------------------------------

_sqlite_conn: sqlite3.Connection | None = None
_sqlite_lock = threading.Lock()


def _sqlite_path() -> Path:
    override = os.environ.get("SQLITE_PATH")
    if override:
        return Path(override)
    # Vercel serverless: only /tmp is writable.
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return Path("/tmp/xbox_checker.db")
    data_dir = BASE_DIR / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir / "xbox_checker.db"


def _get_sqlite_conn() -> sqlite3.Connection:
    global _sqlite_conn
    if _sqlite_conn is None:
        with _sqlite_lock:
            if _sqlite_conn is None:
                path = _sqlite_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(path), check_same_thread=False)
                conn.row_factory = sqlite3.Row
                # Sensible defaults for a small web workload.
                try:
                    conn.execute("PRAGMA journal_mode=WAL;")
                    conn.execute("PRAGMA foreign_keys=ON;")
                except sqlite3.Error:
                    pass
                _sqlite_conn = conn
                log.info("Using SQLite fallback database at %s", path)
    return _sqlite_conn


# ---------------------------------------------------------------------------
# Public async API (shared by both backends)
# ---------------------------------------------------------------------------

_db_ready = False


async def _ensure_ready() -> None:
    """Lazily create tables on first database access.

    The FastAPI ``startup`` handler also calls :func:`init_db`, but serverless
    runtimes and test harnesses don't always trigger it — this guarantees the
    schema exists before any query runs. ``CREATE TABLE IF NOT EXISTS`` makes
    concurrent first-calls safe.
    """
    global _db_ready
    if _db_ready:
        return
    try:
        await init_db()
        _db_ready = True
    except Exception:
        log.warning("Lazy database init failed; will retry on next access", exc_info=True)
        raise


async def _execute_inner(query: str, *args):
    if using_turso():
        client = await _resolve_client()
        result = await client.execute(query, list(args))
        return getattr(result, "rows_affected", 0)
    conn = _get_sqlite_conn()
    with _sqlite_lock:
        cursor = conn.execute(query, tuple(args))
        conn.commit()
        return cursor.rowcount


async def _fetchone_inner(query: str, *args) -> dict | None:
    if using_turso():
        client = await _resolve_client()
        result = await client.execute(query, list(args))
        rows = _result_to_dicts(result)
        return rows[0] if rows else None
    conn = _get_sqlite_conn()
    with _sqlite_lock:
        cursor = conn.execute(query, tuple(args))
        row = cursor.fetchone()
        # Needed for DML statements using ``RETURNING`` (the atomic quota
        # consumer uses this); harmless for ordinary SELECT statements.
        conn.commit()
        return dict(row) if row is not None else None


async def _fetchall_inner(query: str, *args) -> list[dict]:
    if using_turso():
        client = await _resolve_client()
        result = await client.execute(query, list(args))
        return _result_to_dicts(result)
    conn = _get_sqlite_conn()
    with _sqlite_lock:
        cursor = conn.execute(query, tuple(args))
        return [dict(row) for row in cursor.fetchall()]


async def execute(query: str, *args):
    """Run an INSERT/UPDATE/DELETE/DDL statement. Returns affected row count."""
    await _ensure_ready()
    return await _execute_inner(query, *args)


async def fetchone(query: str, *args) -> dict | None:
    await _ensure_ready()
    return await _fetchone_inner(query, *args)


async def fetchall(query: str, *args) -> list[dict]:
    await _ensure_ready()
    return await _fetchall_inner(query, *args)


async def ping() -> bool:
    """Return True when the database answers."""
    try:
        row = await fetchone("SELECT 1 AS ok")
        return bool(row and row.get("ok") == 1)
    except Exception:
        return False


def _split_statements(schema: str) -> list[str]:
    """Split a .sql schema file into individual statements.

    Handles ``--`` line comments and ignores empty statements. The bundled
    schema has no semicolons inside string literals, so a simple split is
    safe here.
    """
    # Remove full-line comments *before* splitting. A comment may itself
    # contain a semicolon and must never turn the preceding CREATE statement
    # into an "incomplete input" deployment failure.
    uncommented = "\n".join(
        line
        for line in schema.splitlines()
        if line.strip() and not line.strip().startswith("--")
    )
    return [statement.strip() for statement in uncommented.split(";") if statement.strip()]


async def init_db() -> None:
    """Create tables from ``migrations/initial.sql`` if they don't exist."""
    global _db_ready
    if not SCHEMA_PATH.exists():
        raise DatabaseNotConfigured(f"Schema file not found: {SCHEMA_PATH}")
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    for stmt in _split_statements(schema):
        await _execute_inner(stmt)
    _db_ready = True
