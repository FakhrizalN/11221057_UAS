"""
Pydantic models for event validation and API responses.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
import uuid


class EventPayload(BaseModel):
    """Flexible payload schema for events."""
    class Config:
        extra = "allow"


class Event(BaseModel):
    """
    Event model representing a log event in the Pub-Sub system.
    
    The (topic, event_id) pair must be unique for deduplication.
    """
    topic: str = Field(..., min_length=1, max_length=255, description="Topic/channel for the event")
    event_id: str = Field(..., min_length=1, max_length=255, description="Unique event identifier")
    timestamp: datetime = Field(..., description="Event timestamp in ISO8601 format")
    source: str = Field(..., min_length=1, max_length=255, description="Source service/component")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event payload data")
    
    @field_validator('event_id')
    @classmethod
    def validate_event_id(cls, v: str) -> str:
        """Ensure event_id is not empty after stripping."""
        if not v.strip():
            raise ValueError('event_id cannot be empty or whitespace')
        return v.strip()
    
    @field_validator('topic')
    @classmethod
    def validate_topic(cls, v: str) -> str:
        """Ensure topic is not empty after stripping."""
        if not v.strip():
            raise ValueError('topic cannot be empty or whitespace')
        return v.strip()


class BatchPublishRequest(BaseModel):
    """Request model for batch event publishing."""
    events: List[Event] = Field(..., min_length=1, max_length=1000, description="List of events to publish")


class PublishResponse(BaseModel):
    """Response model for publish operations."""
    success: bool
    message: str
    received: int = 0
    duplicates: int = 0
    processed: int = 0
    event_ids: List[str] = Field(default_factory=list)


class EventResponse(BaseModel):
    """Response model for a single event."""
    topic: str
    event_id: str
    timestamp: datetime
    source: str
    payload: Dict[str, Any]
    processed_at: datetime


class EventListResponse(BaseModel):
    """Response model for event list queries."""
    events: List[EventResponse]
    total: int
    topic: Optional[str] = None


class TopicStats(BaseModel):
    """Statistics for a single topic."""
    topic: str
    event_count: int


class StatsResponse(BaseModel):
    """Response model for statistics endpoint."""
    received: int
    unique_processed: int
    duplicate_dropped: int
    duplicate_rate: float
    topics: List[TopicStats]
    topic_count: int
    uptime_seconds: float
    started_at: datetime
    last_updated_at: datetime


class HealthResponse(BaseModel):
    """Response model for health check endpoint."""
    status: str
    database: str
    redis: str
    version: str
    uptime_seconds: float
