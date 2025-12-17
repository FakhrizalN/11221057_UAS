"""
Main FastAPI application for the Pub-Sub Log Aggregator.

Endpoints:
- POST /publish: Publish single or batch events
- GET /events: Retrieve processed events with optional topic filter
- GET /stats: Get aggregation statistics
- GET /health: Health check endpoint

Features:
- Idempotent event processing with deduplication
- Atomic transactions for data consistency
- Multi-worker concurrent processing
- Observability through logging and stats
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional, Union

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pythonjsonlogger import jsonlogger

from .config import get_settings
from .models import (
    Event,
    BatchPublishRequest,
    PublishResponse,
    EventListResponse,
    StatsResponse,
    HealthResponse,
)
from .database import (
    init_db,
    close_db,
    process_event,
    process_events_batch,
    get_events,
    get_event_count,
    get_stats,
    check_db_health,
)
from .consumer import (
    init_redis,
    close_redis,
    publish_event,
    publish_events_batch,
    start_workers,
    stop_workers,
    check_redis_health,
)

# Configure logging
settings = get_settings()


def setup_logging():
    """Configure JSON logging for observability."""
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, settings.log_level.upper()))
    
    # JSON formatter for structured logging
    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt='%(asctime)s %(levelname)s %(name)s %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    # Reduce noise from libraries
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)


setup_logging()
logger = logging.getLogger(__name__)

# Track application start time
_start_time: datetime = datetime.now()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    
    Initializes database and Redis connections on startup,
    starts consumer workers, and cleans up on shutdown.
    """
    global _start_time
    _start_time = datetime.now()
    
    logger.info("Starting Pub-Sub Log Aggregator...")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized")
    
    # Initialize Redis
    await init_redis()
    logger.info("Redis initialized")
    
    # Start consumer workers
    await start_workers()
    logger.info("Consumer workers started")
    
    logger.info(f"Application started successfully at {_start_time.isoformat()}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    
    await stop_workers()
    await close_redis()
    await close_db()
    
    logger.info("Application shut down successfully")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "A distributed Pub-Sub log aggregator with idempotent consumer, "
        "deduplication, and transaction/concurrency control."
    ),
    lifespan=lifespan,
)

# Add CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/publish", response_model=PublishResponse)
async def publish(
    request: Union[Event, BatchPublishRequest],
    background_tasks: BackgroundTasks,
    sync: bool = Query(False, description="Process synchronously instead of via queue")
):
    """
    Publish event(s) to the aggregator.
    
    Supports both single event and batch publishing.
    
    - **sync=false** (default): Events are published to Redis queue for async processing
    - **sync=true**: Events are processed synchronously with immediate dedup
    
    The (topic, event_id) pair must be unique. Duplicate events are detected
    and dropped (idempotent processing).
    
    Returns:
        PublishResponse with counts of received, processed, and duplicate events
    """
    # Normalize to list
    if isinstance(request, Event):
        events = [request]
    else:
        events = request.events
    
    logger.info(f"Received {len(events)} events for publishing (sync={sync})")
    
    try:
        if sync:
            # Process synchronously with immediate dedup
            processed, duplicates = await process_events_batch(events, "api-sync")
            
            return PublishResponse(
                success=True,
                message=f"Processed {processed} events, {duplicates} duplicates dropped",
                received=len(events),
                processed=processed,
                duplicates=duplicates,
                event_ids=[e.event_id for e in events]
            )
        else:
            # Publish to Redis for async processing by workers
            published = await publish_events_batch(events)
            
            return PublishResponse(
                success=True,
                message=f"Published {published} events to queue",
                received=len(events),
                processed=0,  # Will be processed async
                duplicates=0,
                event_ids=[e.event_id for e in events]
            )
            
    except Exception as e:
        logger.error(f"Failed to publish events: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to publish: {str(e)}")


@app.get("/events", response_model=EventListResponse)
async def list_events(
    topic: Optional[str] = Query(None, description="Filter by topic"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum events to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """
    Retrieve processed events.
    
    Events are returned in reverse chronological order (newest first).
    Use the `topic` parameter to filter by specific topic.
    
    Returns:
        EventListResponse with list of events and total count
    """
    try:
        events = await get_events(topic=topic, limit=limit, offset=offset)
        total = await get_event_count(topic=topic)
        
        return EventListResponse(
            events=events,
            total=total,
            topic=topic
        )
    except Exception as e:
        logger.error(f"Failed to retrieve events: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve events: {str(e)}")


@app.get("/stats", response_model=StatsResponse)
async def get_statistics():
    """
    Get aggregation statistics.
    
    Returns:
        StatsResponse with:
        - received: Total events received
        - unique_processed: Events successfully processed (unique)
        - duplicate_dropped: Duplicate events dropped
        - duplicate_rate: Percentage of duplicates
        - topics: Breakdown by topic
        - uptime_seconds: Service uptime
    """
    try:
        stats = await get_stats()
        uptime = (datetime.now() - _start_time).total_seconds()
        
        return StatsResponse(
            received=stats['received'],
            unique_processed=stats['unique_processed'],
            duplicate_dropped=stats['duplicate_dropped'],
            duplicate_rate=stats['duplicate_rate'],
            topics=stats['topics'],
            topic_count=stats['topic_count'],
            uptime_seconds=round(uptime, 2),
            started_at=stats['started_at'],
            last_updated_at=stats['last_updated_at']
        )
    except Exception as e:
        logger.error(f"Failed to retrieve stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve stats: {str(e)}")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint for liveness/readiness probes.
    
    Checks connectivity to:
    - PostgreSQL database
    - Redis broker
    
    Returns:
        HealthResponse with status of each dependency
    """
    db_healthy = await check_db_health()
    redis_healthy = await check_redis_health()
    
    uptime = (datetime.now() - _start_time).total_seconds()
    
    status = "healthy" if (db_healthy and redis_healthy) else "unhealthy"
    
    response = HealthResponse(
        status=status,
        database="connected" if db_healthy else "disconnected",
        redis="connected" if redis_healthy else "disconnected",
        version=settings.app_version,
        uptime_seconds=round(uptime, 2)
    )
    
    if status == "unhealthy":
        raise HTTPException(status_code=503, detail=response.model_dump())
    
    return response


@app.get("/")
async def root():
    """Root endpoint with basic info."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health"
    }
