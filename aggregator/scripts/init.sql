-- ============================================
-- Database Schema for Pub-Sub Log Aggregator
-- Idempotent Consumer with Deduplication
-- ============================================

-- Events table with UNIQUE constraint for deduplication
-- The (topic, event_id) pair must be unique to ensure idempotency
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    event_id VARCHAR(255) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    source VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    processed_at TIMESTAMPTZ DEFAULT NOW(),
    worker_id VARCHAR(100),  -- Track which worker processed this event
    
    -- CRITICAL: Unique constraint for deduplication
    -- INSERT ... ON CONFLICT (topic, event_id) DO NOTHING
    CONSTRAINT uq_topic_event_id UNIQUE(topic, event_id)
);

-- Statistics table for atomic counter updates
-- Using singleton pattern (id=1) for simplicity
CREATE TABLE IF NOT EXISTS stats (
    id INTEGER PRIMARY KEY DEFAULT 1,
    received BIGINT DEFAULT 0,
    unique_processed BIGINT DEFAULT 0,
    duplicate_dropped BIGINT DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    last_updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Ensure only one row exists
    CONSTRAINT single_row CHECK (id = 1)
);

-- Audit log for tracking all incoming events (including duplicates)
-- Useful for debugging and observability
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    event_id VARCHAR(255) NOT NULL,
    received_at TIMESTAMPTZ DEFAULT NOW(),
    is_duplicate BOOLEAN DEFAULT FALSE,
    worker_id VARCHAR(100)
);

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_events_topic ON events(topic);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
CREATE INDEX IF NOT EXISTS idx_audit_log_event_id ON audit_log(event_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_received_at ON audit_log(received_at DESC);

-- Initialize stats with a single row
INSERT INTO stats (id, received, unique_processed, duplicate_dropped, started_at)
VALUES (1, 0, 0, 0, NOW())
ON CONFLICT (id) DO NOTHING;

-- Function to get topics list
CREATE OR REPLACE FUNCTION get_distinct_topics()
RETURNS TABLE(topic VARCHAR(255), event_count BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT e.topic, COUNT(*)::BIGINT as event_count
    FROM events e
    GROUP BY e.topic
    ORDER BY event_count DESC;
END;
$$ LANGUAGE plpgsql;
