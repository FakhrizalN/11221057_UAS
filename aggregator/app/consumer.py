"""
Redis consumer module for processing events from the message broker.

Implements:
- Multi-worker concurrent processing
- Redis Pub/Sub subscription
- Graceful shutdown handling
- At-least-once delivery with idempotent processing
"""
import asyncio
import json
import logging
import signal
from typing import Optional, List
from datetime import datetime

import redis.asyncio as redis
from redis.asyncio.client import PubSub

from .config import get_settings
from .models import Event
from .database import process_event, get_pool

logger = logging.getLogger(__name__)

# Global Redis client
_redis_client: Optional[redis.Redis] = None
_shutdown_event: asyncio.Event = asyncio.Event()
_workers: List[asyncio.Task] = []


async def init_redis() -> redis.Redis:
    """
    Initialize Redis connection.
    
    Returns:
        redis.Redis: Redis client instance
    """
    global _redis_client
    settings = get_settings()
    
    logger.info(f"Connecting to Redis: {settings.redis_url}")
    
    _redis_client = redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True
    )
    
    # Test connection
    await _redis_client.ping()
    logger.info("Redis connection established")
    
    return _redis_client


async def close_redis():
    """Close Redis connection."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        logger.info("Redis connection closed")
        _redis_client = None


def get_redis() -> redis.Redis:
    """Get the current Redis client."""
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis() first.")
    return _redis_client


async def check_redis_health() -> bool:
    """Check Redis connectivity."""
    try:
        client = get_redis()
        await client.ping()
        return True
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return False


async def publish_event(event: Event) -> bool:
    """
    Publish an event to the Redis channel.
    
    Args:
        event: Event to publish
        
    Returns:
        bool: True if published successfully
    """
    try:
        client = get_redis()
        settings = get_settings()
        
        # Serialize event to JSON
        event_data = event.model_dump_json()
        
        # Publish to Redis channel
        await client.publish(settings.redis_channel, event_data)
        
        logger.debug(f"Event published: {event.topic}/{event.event_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to publish event: {e}")
        return False


async def publish_events_batch(events: List[Event]) -> int:
    """
    Publish multiple events to the Redis channel.
    
    Args:
        events: List of events to publish
        
    Returns:
        int: Number of events published successfully
    """
    client = get_redis()
    settings = get_settings()
    published = 0
    
    async with client.pipeline() as pipe:
        for event in events:
            event_data = event.model_dump_json()
            pipe.publish(settings.redis_channel, event_data)
        
        results = await pipe.execute()
        published = sum(1 for r in results if r > 0)
    
    logger.debug(f"Batch published: {published}/{len(events)} events")
    return published


async def worker(worker_id: str):
    """
    Worker coroutine that processes events from Redis Pub/Sub.
    
    Implements at-least-once delivery:
    - Events may be received multiple times (Redis Pub/Sub)
    - Idempotent processing ensures no duplicate side effects
    
    Args:
        worker_id: Unique identifier for this worker
    """
    settings = get_settings()
    client = get_redis()
    pubsub: PubSub = client.pubsub()
    
    try:
        await pubsub.subscribe(settings.redis_channel)
        logger.info(f"[{worker_id}] Subscribed to channel: {settings.redis_channel}")
        
        while not _shutdown_event.is_set():
            try:
                # Get message with timeout to allow shutdown checks
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                    timeout=2.0
                )
                
                if message is None:
                    continue
                
                if message['type'] != 'message':
                    continue
                
                # Parse event
                try:
                    event_data = json.loads(message['data'])
                    event = Event(**event_data)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"[{worker_id}] Invalid event data: {e}")
                    continue
                
                # Process event with idempotent handling
                success, is_duplicate = await process_event(event, worker_id)
                
                if success:
                    if is_duplicate:
                        logger.debug(f"[{worker_id}] Duplicate dropped: {event.event_id}")
                    else:
                        logger.debug(f"[{worker_id}] Processed: {event.event_id}")
                        
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info(f"[{worker_id}] Cancelled, shutting down...")
                break
            except Exception as e:
                logger.error(f"[{worker_id}] Error processing message: {e}")
                await asyncio.sleep(0.1)  # Brief backoff on error
                
    finally:
        await pubsub.unsubscribe(settings.redis_channel)
        await pubsub.close()
        logger.info(f"[{worker_id}] Worker stopped")


async def start_workers(num_workers: Optional[int] = None):
    """
    Start multiple worker coroutines for concurrent event processing.
    
    This demonstrates concurrent processing where multiple workers
    may receive the same event (fan-out). Idempotent processing
    ensures only one worker successfully processes each unique event.
    
    Args:
        num_workers: Number of workers to start (default from config)
    """
    global _workers
    settings = get_settings()
    
    if num_workers is None:
        num_workers = settings.worker_count
    
    logger.info(f"Starting {num_workers} consumer workers...")
    
    _workers = [
        asyncio.create_task(worker(f"worker-{i}"))
        for i in range(num_workers)
    ]
    
    logger.info(f"{num_workers} workers started")


async def stop_workers():
    """Stop all running workers gracefully."""
    global _workers
    
    logger.info("Stopping workers...")
    _shutdown_event.set()
    
    if _workers:
        # Cancel all workers
        for w in _workers:
            w.cancel()
        
        # Wait for all workers to complete
        await asyncio.gather(*_workers, return_exceptions=True)
        _workers = []
    
    logger.info("All workers stopped")


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown."""
    loop = asyncio.get_event_loop()
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(
                sig,
                lambda: asyncio.create_task(stop_workers())
            )
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass
