-- Command mutations and their reply are committed together.
CREATE TABLE IF NOT EXISTS imessage_inbound_events (
    address TEXT NOT NULL,
    message_id TEXT NOT NULL,
    reply TEXT,
    PRIMARY KEY (address, message_id)
);
