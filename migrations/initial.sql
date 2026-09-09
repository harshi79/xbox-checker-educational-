-- Users & Authentication
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    -- SHA-256 digest record plus a non-secret display preview, never plaintext.
    api_key TEXT UNIQUE NOT NULL,
    tier TEXT DEFAULT 'free' CHECK (tier IN ('free', 'premium', 'pro')),
    -- Legacy column name: contains a random browser installation ID only.
    device_fingerprint TEXT NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key);
CREATE INDEX IF NOT EXISTS idx_users_fingerprint ON users(device_fingerprint);

-- Distributed authentication throttling. Identifiers are one-way hashes of
-- scope + client address/email and never contain the source values.
CREATE TABLE IF NOT EXISTS auth_attempts (
    key_hash TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    window_started_at TEXT NOT NULL,
    last_attempt_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_attempts_last ON auth_attempts(last_attempt_at);

-- Browser Sessions
-- Only a SHA-256 digest of the opaque cookie is stored. A database leak cannot
-- be used to replay a live browser session.
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    -- Legacy nullable field retained for schema compatibility; new sessions
    -- do not collect browser user-agent fingerprints.
    user_agent_hash TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);

-- One-time Microsoft OAuth state. The raw state is never stored, and the
-- short-lived Microsoft access token is never persisted at all.
CREATE TABLE IF NOT EXISTS oauth_states (
    state_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    code_verifier TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_oauth_states_expires_at ON oauth_states(expires_at);

-- Minimal, non-secret Xbox profile snapshot obtained with explicit consent.
CREATE TABLE IF NOT EXISTS xbox_connections (
    user_id INTEGER PRIMARY KEY,
    xuid TEXT,
    gamertag TEXT NOT NULL,
    gamerscore INTEGER DEFAULT 0,
    account_tier TEXT,
    connected_at TEXT NOT NULL,
    last_checked_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Daily Usage Tracking
CREATE TABLE IF NOT EXISTS daily_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    check_date TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    tier_limit INTEGER NOT NULL,
    UNIQUE(user_id, check_date),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Consent/security audit events. Metadata is optional non-secret JSON only.
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_audit_events_user_created
    ON audit_events(user_id, created_at);

-- Admin Configuration
CREATE TABLE IF NOT EXISTS admin_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO admin_config (key, value) VALUES 
    ('free_limit', '100'),
    ('premium_limit', '1000'),
    ('pro_limit', '999999');
