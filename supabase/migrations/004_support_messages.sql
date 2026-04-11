-- Support / contact messages from users to bot owner
CREATE TABLE IF NOT EXISTS support_messages (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    telegram_id     BIGINT  NOT NULL,
    username        TEXT    NOT NULL DEFAULT '',
    message         TEXT    NOT NULL,
    category        TEXT    NOT NULL DEFAULT 'general',   -- general, bug, feature
    is_read         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_support_messages_is_read ON support_messages (is_read);
CREATE INDEX idx_support_messages_created_at ON support_messages (created_at DESC);
