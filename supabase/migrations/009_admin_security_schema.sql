-- =============================================================================
-- Migration 009: Admin security schema
--
-- Creates the security.* schema with all tables required for admin authentication,
-- RBAC, TOTP, refresh-token rotation, audit, and idempotency.
--
-- Admin accounts are completely independent from Telegram users. They do NOT
-- carry telegram_id and web privileges are NOT derived from ADMIN_TELEGRAM_ID.
--
-- Account states: invited -> pending_totp -> active -> suspended | disabled
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS security;

-- =============================================================================
-- Table: security.admin_accounts
-- =============================================================================
CREATE TABLE IF NOT EXISTS security.admin_accounts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               TEXT UNIQUE NOT NULL,
    display_name        TEXT NOT NULL,
    password_hash       TEXT,
    status              TEXT NOT NULL DEFAULT 'invited'
                        CHECK (status IN ('invited', 'pending_totp', 'active', 'suspended', 'disabled')),
    authz_version       INTEGER NOT NULL DEFAULT 1,
    password_changed_at TIMESTAMPTZ,
    last_login_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at         TIMESTAMPTZ,
    created_by          UUID REFERENCES security.admin_accounts(id),
    row_version         INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_admin_accounts_email
    ON security.admin_accounts (lower(email));
CREATE INDEX IF NOT EXISTS idx_admin_accounts_status
    ON security.admin_accounts (status);

-- =============================================================================
-- Table: security.admin_roles
-- =============================================================================
CREATE TABLE IF NOT EXISTS security.admin_roles (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    description TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- Table: security.admin_permissions
-- =============================================================================
CREATE TABLE IF NOT EXISTS security.admin_permissions (
    id          SERIAL PRIMARY KEY,
    key         TEXT UNIQUE NOT NULL,
    description TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- Table: security.admin_role_permissions
-- =============================================================================
CREATE TABLE IF NOT EXISTS security.admin_role_permissions (
    role_id       INTEGER NOT NULL REFERENCES security.admin_roles(id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES security.admin_permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

-- =============================================================================
-- Table: security.admin_account_roles
-- =============================================================================
CREATE TABLE IF NOT EXISTS security.admin_account_roles (
    account_id  UUID NOT NULL REFERENCES security.admin_accounts(id) ON DELETE CASCADE,
    role_id     INTEGER NOT NULL REFERENCES security.admin_roles(id) ON DELETE CASCADE,
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by  UUID REFERENCES security.admin_accounts(id),
    PRIMARY KEY (account_id, role_id)
);

-- =============================================================================
-- Table: security.admin_refresh_sessions
-- =============================================================================
CREATE TABLE IF NOT EXISTS security.admin_refresh_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES security.admin_accounts(id) ON DELETE CASCADE,
    family_id       UUID NOT NULL,
    token_hash      TEXT NOT NULL,
    expires_at       TIMESTAMPTZ NOT NULL,
    revoked         BOOLEAN NOT NULL DEFAULT FALSE,
    revoked_at      TIMESTAMPTZ,
    revoked_reason  TEXT,
    reused          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_refresh_sessions_account
    ON security.admin_refresh_sessions (account_id);
CREATE INDEX IF NOT EXISTS idx_refresh_sessions_family
    ON security.admin_refresh_sessions (family_id);
CREATE INDEX IF NOT EXISTS idx_refresh_sessions_token_hash
    ON security.admin_refresh_sessions (token_hash);
CREATE INDEX IF NOT EXISTS idx_refresh_sessions_active
    ON security.admin_refresh_sessions (account_id, revoked, expires_at)
    WHERE revoked = FALSE;

-- =============================================================================
-- Table: security.admin_totp_credentials
-- =============================================================================
CREATE TABLE IF NOT EXISTS security.admin_totp_credentials (
    account_id      UUID PRIMARY KEY REFERENCES security.admin_accounts(id) ON DELETE CASCADE,
    secret_encrypted BYTEA NOT NULL,
    enrolled_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- Table: security.admin_recovery_codes
-- =============================================================================
CREATE TABLE IF NOT EXISTS security.admin_recovery_codes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id  UUID NOT NULL REFERENCES security.admin_accounts(id) ON DELETE CASCADE,
    code_hash   TEXT NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_recovery_codes_account
    ON security.admin_recovery_codes (account_id)
    WHERE used_at IS NULL;

-- =============================================================================
-- Table: security.admin_action_tokens
-- =============================================================================
CREATE TABLE IF NOT EXISTS security.admin_action_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id  UUID NOT NULL REFERENCES security.admin_accounts(id) ON DELETE CASCADE,
    token_type  TEXT NOT NULL CHECK (token_type IN ('invitation', 'password_reset')),
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_by  UUID REFERENCES security.admin_accounts(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_action_tokens_account
    ON security.admin_action_tokens (account_id);
CREATE INDEX IF NOT EXISTS idx_action_tokens_type
    ON security.admin_action_tokens (token_type, expires_at)
    WHERE used_at IS NULL;

-- =============================================================================
-- Table: security.admin_audit_events
-- =============================================================================
CREATE TABLE IF NOT EXISTS security.admin_audit_events (
    id              BIGSERIAL PRIMARY KEY,
    account_id      UUID REFERENCES security.admin_accounts(id),
    event_type      TEXT NOT NULL,
    detail          JSONB DEFAULT '{}',
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_account
    ON security.admin_audit_events (account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_type
    ON security.admin_audit_events (event_type, created_at DESC);

-- =============================================================================
-- Table: security.admin_idempotency_records
-- =============================================================================
CREATE TABLE IF NOT EXISTS security.admin_idempotency_records (
    key_hash        TEXT PRIMARY KEY,
    account_id      UUID REFERENCES security.admin_accounts(id) ON DELETE CASCADE,
    response_hash   TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- Trigger: auto-update updated_at on admin_accounts
-- =============================================================================
CREATE OR REPLACE FUNCTION security.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER admin_accounts_updated_at
    BEFORE UPDATE ON security.admin_accounts
    FOR EACH ROW
    EXECUTE FUNCTION security.update_updated_at();

-- =============================================================================
-- Seed: permissions
-- =============================================================================
INSERT INTO security.admin_permissions (key, description) VALUES
    ('dashboard.read',         'View the admin dashboard'),
    ('jobs.read',              'View job listings'),
    ('jobs.manage',            'Create, update, and requeue jobs'),
    ('jobs.archive',           'Archive jobs'),
    ('jobs.delete',            'Permanently delete jobs'),
    ('telegram-users.read',    'View Telegram users'),
    ('telegram-users.manage',  'Manage Telegram users'),
    ('runs.read',              'View bot run history'),
    ('runs.trigger',           'Trigger a manual run'),
    ('runs.cancel',            'Cancel a running job'),
    ('sources.read',           'View job sources'),
    ('sources.manage',         'Configure job sources'),
    ('sources.probe',          'Probe a source for health'),
    ('deliveries.read',        'View delivery queue'),
    ('deliveries.replay',      'Replay dead-letter deliveries'),
    ('deliveries.cancel',      'Cancel pending deliveries'),
    ('support.read',           'View support messages'),
    ('support.reply',          'Reply to support messages'),
    ('support.manage',         'Manage support tickets'),
    ('broadcasts.read',        'View broadcast history'),
    ('broadcasts.create',      'Create a broadcast'),
    ('broadcasts.dispatch',    'Dispatch a broadcast'),
    ('settings.read',          'View system settings'),
    ('settings.manage',        'Modify system settings'),
    ('admins.read',            'View admin accounts'),
    ('admins.manage',          'Create, suspend, and disable admin accounts'),
    ('roles.manage',           'Manage roles and permissions'),
    ('audit.read',             'View audit events'),
    ('audit.export',           'Export audit events'),
    ('system.destructive',      'Perform destructive operations')
ON CONFLICT (key) DO NOTHING;

-- =============================================================================
-- Seed: super_admin role with all permissions
-- =============================================================================
INSERT INTO security.admin_roles (name, description)
VALUES ('super_admin', 'Full access — all permissions')
ON CONFLICT (name) DO NOTHING;

INSERT INTO security.admin_role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM security.admin_roles r, security.admin_permissions p
WHERE r.name = 'super_admin'
ON CONFLICT DO NOTHING;

-- =============================================================================
-- Seed: read_only role with read permissions only
-- =============================================================================
INSERT INTO security.admin_roles (name, description)
VALUES ('read_only', 'Read-only access to dashboard data')
ON CONFLICT (name) DO NOTHING;

INSERT INTO security.admin_role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM security.admin_roles r, security.admin_permissions p
WHERE r.name = 'read_only'
  AND p.key LIKE '%%.read'
ON CONFLICT DO NOTHING;

-- =============================================================================
-- Row Level Security (defense in depth — app connects as superuser, but
-- enforce at the schema level for any future role-based access)
-- =============================================================================
ALTER TABLE security.admin_accounts           ENABLE ROW LEVEL SECURITY;
ALTER TABLE security.admin_roles               ENABLE ROW LEVEL SECURITY;
ALTER TABLE security.admin_permissions         ENABLE ROW LEVEL SECURITY;
ALTER TABLE security.admin_role_permissions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE security.admin_account_roles       ENABLE ROW LEVEL SECURITY;
ALTER TABLE security.admin_refresh_sessions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE security.admin_totp_credentials    ENABLE ROW LEVEL SECURITY;
ALTER TABLE security.admin_recovery_codes       ENABLE ROW LEVEL SECURITY;
ALTER TABLE security.admin_action_tokens       ENABLE ROW LEVEL SECURITY;
ALTER TABLE security.admin_audit_events        ENABLE ROW LEVEL SECURITY;
ALTER TABLE security.admin_idempotency_records ENABLE ROW LEVEL SECURITY;
