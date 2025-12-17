"""
Publisher Service - Event Generator for Pub-Sub Log Aggregator

This service generates simulated log events and publishes them to the
aggregator system. It supports:

- Configurable event count
- Configurable duplicate rate (default 35%)
- Multiple topics
- Batch publishing for performance
- Both Redis (queue) and HTTP (direct) publishing modes

The duplicate injection is intentional to test the idempotent consumer
and deduplication mechanisms of the aggregator.
"""
import asyncio
import json
import logging
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any

import httpx
import redis.asyncio as redis
from faker import Faker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s - %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Initialize Faker for realistic data
fake = Faker()


class Config:
    """Publisher configuration from environment variables."""
    
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    AGGREGATOR_URL: str = os.getenv("AGGREGATOR_URL", "http://localhost:8080")
    EVENT_COUNT: int = int(os.getenv("EVENT_COUNT", "25000"))
    DUPLICATE_RATE: float = float(os.getenv("DUPLICATE_RATE", "0.35"))
    BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "100"))
    DELAY_MS: int = int(os.getenv("DELAY_MS", "10"))
    REDIS_CHANNEL: str = os.getenv("REDIS_CHANNEL", "events")
    MODE: str = os.getenv("PUBLISH_MODE", "redis")  # 'redis' or 'http'
    
    # Topics to generate events for
    TOPICS: List[str] = [
        "app.users.login",
        "app.users.logout",
        "app.orders.created",
        "app.orders.completed",
        "app.payments.processed",
        "app.errors.critical",
        "app.errors.warning",
        "system.health.check",
        "system.metrics.cpu",
        "system.metrics.memory"
    ]
    
    # Sources (simulated services)
    SOURCES: List[str] = [
        "auth-service",
        "order-service",
        "payment-service",
        "notification-service",
        "monitoring-service"
    ]


def generate_event(event_id: str = None, topic: str = None) -> Dict[str, Any]:
    """
    Generate a single log event.
    
    Args:
        event_id: Optional specific event_id (for duplicates)
        topic: Optional specific topic
        
    Returns:
        Dict representing the event
    """
    if event_id is None:
        event_id = str(uuid.uuid4())
    
    if topic is None:
        topic = random.choice(Config.TOPICS)
    
    source = random.choice(Config.SOURCES)
    
    # Generate realistic payload based on topic
    if "login" in topic:
        payload = {
            "user_id": fake.uuid4(),
            "username": fake.user_name(),
            "ip_address": fake.ipv4(),
            "user_agent": fake.user_agent()
        }
    elif "order" in topic:
        payload = {
            "order_id": fake.uuid4(),
            "customer_id": fake.uuid4(),
            "amount": round(random.uniform(10, 1000), 2),
            "currency": "USD",
            "items": random.randint(1, 10)
        }
    elif "payment" in topic:
        payload = {
            "payment_id": fake.uuid4(),
            "order_id": fake.uuid4(),
            "amount": round(random.uniform(10, 1000), 2),
            "method": random.choice(["credit_card", "debit_card", "paypal", "bank_transfer"]),
            "status": random.choice(["success", "pending", "failed"])
        }
    elif "error" in topic:
        payload = {
            "error_code": f"ERR_{random.randint(1000, 9999)}",
            "message": fake.sentence(),
            "stack_trace": fake.text(max_nb_chars=200),
            "severity": "critical" if "critical" in topic else "warning"
        }
    elif "metrics" in topic:
        payload = {
            "host": fake.hostname(),
            "value": round(random.uniform(0, 100), 2),
            "unit": "percent" if "cpu" in topic or "memory" in topic else "count",
            "tags": {"env": random.choice(["prod", "staging", "dev"])}
        }
    else:
        payload = {
            "message": fake.sentence(),
            "details": fake.text(max_nb_chars=100)
        }
    
    return {
        "topic": topic,
        "event_id": event_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "payload": payload
    }


def generate_events_with_duplicates(
    total_count: int,
    duplicate_rate: float
) -> List[Dict[str, Any]]:
    """
    Generate a list of events with intentional duplicates.
    
    The duplicate rate determines what percentage of events are duplicates
    of previously generated events.
    
    Args:
        total_count: Total number of events to generate
        duplicate_rate: Rate of duplicates (0.0 to 1.0)
        
    Returns:
        List of events with duplicates mixed in
    """
    events = []
    unique_events = []  # Store unique events for duplication
    
    unique_count = int(total_count * (1 - duplicate_rate))
    duplicate_count = total_count - unique_count
    
    logger.info(f"Generating {unique_count} unique events and {duplicate_count} duplicates")
    
    # Generate unique events first
    for _ in range(unique_count):
        event = generate_event()
        events.append(event)
        unique_events.append(event)
    
    # Generate duplicates by copying existing events
    for _ in range(duplicate_count):
        if unique_events:
            # Pick a random existing event to duplicate
            original = random.choice(unique_events)
            # Create duplicate with same topic and event_id
            duplicate = generate_event(
                event_id=original["event_id"],
                topic=original["topic"]
            )
            # Keep original timestamp to simulate retransmission
            duplicate["timestamp"] = original["timestamp"]
            events.append(duplicate)
    
    # Shuffle to mix duplicates with originals
    random.shuffle(events)
    
    return events


async def publish_via_redis(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Publish events via Redis Pub/Sub.
    
    Args:
        events: List of events to publish
        
    Returns:
        Dict with publishing statistics
    """
    logger.info(f"Publishing {len(events)} events via Redis...")
    
    client = redis.from_url(Config.REDIS_URL, decode_responses=True)
    
    try:
        published = 0
        start_time = time.time()
        
        # Publish in batches
        for i in range(0, len(events), Config.BATCH_SIZE):
            batch = events[i:i + Config.BATCH_SIZE]
            
            async with client.pipeline() as pipe:
                for event in batch:
                    pipe.publish(Config.REDIS_CHANNEL, json.dumps(event))
                
                results = await pipe.execute()
                published += sum(1 for r in results if r > 0)
            
            # Progress logging
            if (i + Config.BATCH_SIZE) % 5000 == 0 or i + Config.BATCH_SIZE >= len(events):
                progress = min(i + Config.BATCH_SIZE, len(events))
                logger.info(f"Progress: {progress}/{len(events)} events published")
            
            # Small delay to prevent overwhelming the system
            if Config.DELAY_MS > 0:
                await asyncio.sleep(Config.DELAY_MS / 1000)
        
        elapsed = time.time() - start_time
        rate = published / elapsed if elapsed > 0 else 0
        
        return {
            "mode": "redis",
            "total_events": len(events),
            "published": published,
            "elapsed_seconds": round(elapsed, 2),
            "events_per_second": round(rate, 2)
        }
        
    finally:
        await client.close()


async def publish_via_http(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Publish events via HTTP to the aggregator API.
    
    Args:
        events: List of events to publish
        
    Returns:
        Dict with publishing statistics
    """
    logger.info(f"Publishing {len(events)} events via HTTP...")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        published = 0
        duplicates_reported = 0
        start_time = time.time()
        
        # Publish in batches
        for i in range(0, len(events), Config.BATCH_SIZE):
            batch = events[i:i + Config.BATCH_SIZE]
            
            try:
                response = await client.post(
                    f"{Config.AGGREGATOR_URL}/publish?sync=true",
                    json={"events": batch}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    published += result.get("processed", 0)
                    duplicates_reported += result.get("duplicates", 0)
                else:
                    logger.warning(f"Batch publish failed: {response.status_code}")
                    
            except Exception as e:
                logger.error(f"HTTP publish error: {e}")
            
            # Progress logging
            if (i + Config.BATCH_SIZE) % 5000 == 0 or i + Config.BATCH_SIZE >= len(events):
                progress = min(i + Config.BATCH_SIZE, len(events))
                logger.info(f"Progress: {progress}/{len(events)} events sent")
            
            # Small delay
            if Config.DELAY_MS > 0:
                await asyncio.sleep(Config.DELAY_MS / 1000)
        
        elapsed = time.time() - start_time
        rate = len(events) / elapsed if elapsed > 0 else 0
        
        return {
            "mode": "http",
            "total_events": len(events),
            "unique_processed": published,
            "duplicates_dropped": duplicates_reported,
            "elapsed_seconds": round(elapsed, 2),
            "events_per_second": round(rate, 2)
        }


async def wait_for_aggregator(max_retries: int = 30, delay: float = 2.0):
    """Wait for the aggregator service to be ready."""
    logger.info(f"Waiting for aggregator at {Config.AGGREGATOR_URL}...")
    
    async with httpx.AsyncClient() as client:
        for i in range(max_retries):
            try:
                response = await client.get(f"{Config.AGGREGATOR_URL}/health")
                if response.status_code == 200:
                    logger.info("Aggregator is ready!")
                    return True
            except Exception:
                pass
            
            logger.info(f"Retry {i + 1}/{max_retries}...")
            await asyncio.sleep(delay)
    
    logger.error("Aggregator not available after maximum retries")
    return False


async def get_final_stats() -> Dict[str, Any]:
    """Get final statistics from the aggregator."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{Config.AGGREGATOR_URL}/stats")
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
    return {}


async def main():
    """Main entry point for the publisher."""
    logger.info("=" * 60)
    logger.info("Pub-Sub Log Aggregator - Event Publisher")
    logger.info("=" * 60)
    logger.info(f"Configuration:")
    logger.info(f"  - Event Count: {Config.EVENT_COUNT}")
    logger.info(f"  - Duplicate Rate: {Config.DUPLICATE_RATE * 100:.1f}%")
    logger.info(f"  - Batch Size: {Config.BATCH_SIZE}")
    logger.info(f"  - Publish Mode: {Config.MODE}")
    logger.info(f"  - Topics: {len(Config.TOPICS)}")
    logger.info("=" * 60)
    
    # Wait for aggregator to be ready
    if not await wait_for_aggregator():
        logger.error("Exiting: aggregator not available")
        sys.exit(1)
    
    # Get initial stats
    initial_stats = await get_final_stats()
    logger.info(f"Initial stats: {json.dumps(initial_stats, indent=2)}")
    
    # Generate events with duplicates
    logger.info("Generating events...")
    events = generate_events_with_duplicates(
        Config.EVENT_COUNT,
        Config.DUPLICATE_RATE
    )
    logger.info(f"Generated {len(events)} events")
    
    # Publish events
    if Config.MODE == "http":
        result = await publish_via_http(events)
    else:
        result = await publish_via_redis(events)
    
    logger.info("=" * 60)
    logger.info("Publishing completed!")
    logger.info(f"Results: {json.dumps(result, indent=2)}")
    
    # Wait a moment for async processing to complete
    if Config.MODE == "redis":
        logger.info("Waiting for async processing to complete...")
        await asyncio.sleep(5)
    
    # Get final stats
    final_stats = await get_final_stats()
    logger.info("=" * 60)
    logger.info("Final Aggregator Statistics:")
    logger.info(f"{json.dumps(final_stats, indent=2)}")
    logger.info("=" * 60)
    
    # Summary
    if final_stats:
        received = final_stats.get("received", 0)
        unique = final_stats.get("unique_processed", 0)
        dupes = final_stats.get("duplicate_dropped", 0)
        rate = final_stats.get("duplicate_rate", 0)
        
        logger.info("Summary:")
        logger.info(f"  - Total Received: {received}")
        logger.info(f"  - Unique Processed: {unique}")
        logger.info(f"  - Duplicates Dropped: {dupes}")
        logger.info(f"  - Duplicate Rate: {rate}%")
        
        # Verify expected vs actual
        expected_unique = int(Config.EVENT_COUNT * (1 - Config.DUPLICATE_RATE))
        logger.info(f"  - Expected Unique: ~{expected_unique}")
        
        if unique > 0:
            accuracy = (unique / expected_unique) * 100
            logger.info(f"  - Accuracy: {accuracy:.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
