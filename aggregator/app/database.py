"""
Database module for PostgreSQL connection and transaction management.

Implements:
- Connection pooling with asyncpg
- Transaction context managers
- Idempotent event processing with ON CONFLICT DO NOTHING
- Atomic statistics updates
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from contextlib import asynccontextmanager

import asyncpg
from asyncpg import Pool, Connection

from .config import get_settings
from .models import Event, EventResponse, TopicStats

logger = logging.getLogger(__name__)

# Global connection pool
_pool: Optional[Pool] = None


async def init_db() -> Pool:
    """
    Initialize the database connection pool.
    
    Returns:
        asyncpg.Pool: Connection pool instance
    """
    global _pool
    settings = get_settings()
    
    logger.info(f"Connecting to database: {settings.database_url.split('@')[-1]}")
    
    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=5,
        max_size=20,
        command_timeout=60,
        statement_cache_size=100,
    )
    
    logger.info("Database connection pool established")
    return _pool


async def close_db():
    """Close the database connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        logger.info("Database connection pool closed")
        _pool = None


def get_pool() -> Pool:
    """Get the current connection pool."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db() first.")
    return _pool


@asynccontextmanager
async def get_connection():
    """
    Get a database connection from the pool.
    
    Yields:
        asyncpg.Connection: Database connection
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def transaction(conn: Connection):
    """
    Transaction context manager with automatic commit/rollback.
    
    Uses READ COMMITTED isolation level (PostgreSQL default).
    This is sufficient for our deduplication strategy because:
    1. UNIQUE constraints are enforced at statement level
    2. ON CONFLICT DO NOTHING is atomic
    3. Counter updates use atomic increment (count = count + 1)
    
    Args:
        conn: Database connection
        
    Yields:
        asyncpg.Connection: Connection within transaction
    """
    tr = conn.transaction()
    await tr.start()
    try:
        yield conn
        await tr.commit()
    except Exception as e:
        await tr.rollback()
        logger.error(f"Transaction rolled back: {e}")
        raise


async def process_event(
    event: Event,
    worker_id: str = "main"
) -> Tuple[bool, bool]:
    """
    Process an event with idempotent insert.
    
    This is the core deduplication logic:
    1. Attempt INSERT with ON CONFLICT (topic, event_id) DO NOTHING
    2. If insert succeeds (RETURNING id), event is new -> update unique_processed
    3. If insert fails (no row returned), event is duplicate -> update duplicate_dropped
    4. Always increment received counter
    5. Log to audit_log for observability
    
    All operations are within a single transaction to ensure consistency.
    
    Args:
        event: Event to process
        worker_id: Identifier of the processing worker
        
    Returns:
        Tuple[bool, bool]: (success, is_duplicate)
            - success: Whether the operation completed successfully
            - is_duplicate: Whether the event was a duplicate
    """
    async with get_connection() as conn:
        async with transaction(conn):
            # Attempt idempotent insert
            # ON CONFLICT DO NOTHING ensures atomic deduplication
            result = await conn.fetchrow(
                """
                INSERT INTO events (topic, event_id, timestamp, source, payload, worker_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (topic, event_id) DO NOTHING
                RETURNING id
                """,
                event.topic,
                event.event_id,
                event.timestamp,
                event.source,
                event.payload,
                worker_id
            )
            
            is_duplicate = result is None
            
            # Update statistics atomically
            # Using count = count + 1 prevents lost updates
            await conn.execute(
                """
                UPDATE stats 
                SET received = received + 1,
                    unique_processed = unique_processed + $1,
                    duplicate_dropped = duplicate_dropped + $2,
                    last_updated_at = NOW()
                WHERE id = 1
                """,
                0 if is_duplicate else 1,
                1 if is_duplicate else 0
            )
            
            # Log to audit for observability
            await conn.execute(
                """
                INSERT INTO audit_log (topic, event_id, is_duplicate, worker_id)
                VALUES ($1, $2, $3, $4)
                """,
                event.topic,
                event.event_id,
                is_duplicate,
                worker_id
            )
            
            if is_duplicate:
                logger.debug(f"[{worker_id}] Duplicate event dropped: {event.topic}/{event.event_id}")
            else:
                logger.debug(f"[{worker_id}] New event processed: {event.topic}/{event.event_id}")
            
            return True, is_duplicate


async def process_events_batch(
    events: List[Event],
    worker_id: str = "main"
) -> Tuple[int, int]:
    """
    Process a batch of events atomically.
    
    Each event is processed individually within the same transaction.
    This ensures all-or-nothing semantics for the batch.
    
    Args:
        events: List of events to process
        worker_id: Identifier of the processing worker
        
    Returns:
        Tuple[int, int]: (processed_count, duplicate_count)
    """
    processed = 0
    duplicates = 0
    
    async with get_connection() as conn:
        async with transaction(conn):
            for event in events:
                # Attempt idempotent insert
                result = await conn.fetchrow(
                    """
                    INSERT INTO events (topic, event_id, timestamp, source, payload, worker_id)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (topic, event_id) DO NOTHING
                    RETURNING id
                    """,
                    event.topic,
                    event.event_id,
                    event.timestamp,
                    event.source,
                    event.payload,
                    worker_id
                )
                
                is_duplicate = result is None
                if is_duplicate:
                    duplicates += 1
                else:
                    processed += 1
                
                # Log to audit
                await conn.execute(
                    """
                    INSERT INTO audit_log (topic, event_id, is_duplicate, worker_id)
                    VALUES ($1, $2, $3, $4)
                    """,
                    event.topic,
                    event.event_id,
                    is_duplicate,
                    worker_id
                )
            
            # Update statistics atomically for the batch
            await conn.execute(
                """
                UPDATE stats 
                SET received = received + $1,
                    unique_processed = unique_processed + $2,
                    duplicate_dropped = duplicate_dropped + $3,
                    last_updated_at = NOW()
                WHERE id = 1
                """,
                len(events),
                processed,
                duplicates
            )
    
    logger.info(f"[{worker_id}] Batch processed: {processed} new, {duplicates} duplicates")
    return processed, duplicates


async def get_events(
    topic: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[EventResponse]:
    """
    Retrieve events from the database.
    
    Args:
        topic: Optional topic filter
        limit: Maximum number of events to return
        offset: Offset for pagination
        
    Returns:
        List of EventResponse objects
    """
    async with get_connection() as conn:
        if topic:
            rows = await conn.fetch(
                """
                SELECT topic, event_id, timestamp, source, payload, processed_at
                FROM events
                WHERE topic = $1
                ORDER BY timestamp DESC
                LIMIT $2 OFFSET $3
                """,
                topic, limit, offset
            )
        else:
            rows = await conn.fetch(
                """
                SELECT topic, event_id, timestamp, source, payload, processed_at
                FROM events
                ORDER BY timestamp DESC
                LIMIT $1 OFFSET $2
                """,
                limit, offset
            )
        
        return [
            EventResponse(
                topic=row['topic'],
                event_id=row['event_id'],
                timestamp=row['timestamp'],
                source=row['source'],
                payload=row['payload'],
                processed_at=row['processed_at']
            )
            for row in rows
        ]


async def get_event_count(topic: Optional[str] = None) -> int:
    """Get total event count, optionally filtered by topic."""
    async with get_connection() as conn:
        if topic:
            result = await conn.fetchval(
                "SELECT COUNT(*) FROM events WHERE topic = $1",
                topic
            )
        else:
            result = await conn.fetchval("SELECT COUNT(*) FROM events")
        return result or 0


async def get_stats() -> Dict[str, Any]:
    """
    Get aggregated statistics.
    
    Returns stats from the singleton stats table along with
    computed values like duplicate_rate and topic breakdown.
    """
    async with get_connection() as conn:
        # Get main stats
        stats_row = await conn.fetchrow(
            """
            SELECT received, unique_processed, duplicate_dropped, 
                   started_at, last_updated_at
            FROM stats WHERE id = 1
            """
        )
        
        # Get topic breakdown
        topic_rows = await conn.fetch(
            """
            SELECT topic, COUNT(*) as event_count
            FROM events
            GROUP BY topic
            ORDER BY event_count DESC
            """
        )
        
        if stats_row is None:
            return {
                'received': 0,
                'unique_processed': 0,
                'duplicate_dropped': 0,
                'duplicate_rate': 0.0,
                'topics': [],
                'topic_count': 0,
                'started_at': datetime.now(),
                'last_updated_at': datetime.now(),
            }
        
        received = stats_row['received']
        duplicate_rate = (
            stats_row['duplicate_dropped'] / received * 100
            if received > 0 else 0.0
        )
        
        topics = [
            TopicStats(topic=row['topic'], event_count=row['event_count'])
            for row in topic_rows
        ]
        
        return {
            'received': received,
            'unique_processed': stats_row['unique_processed'],
            'duplicate_dropped': stats_row['duplicate_dropped'],
            'duplicate_rate': round(duplicate_rate, 2),
            'topics': topics,
            'topic_count': len(topics),
            'started_at': stats_row['started_at'],
            'last_updated_at': stats_row['last_updated_at'],
        }


async def check_db_health() -> bool:
    """Check database connectivity."""
    try:
        async with get_connection() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False
