"""
API Tests

These tests verify the API endpoints work correctly:
1. POST /publish - single and batch events
2. GET /events - with and without topic filter
3. GET /stats - statistics endpoint
4. GET /health - health check
5. Schema validation for events
"""
import pytest
import httpx
from uuid import uuid4
from datetime import datetime, timezone


pytestmark = pytest.mark.integration


class TestPublishAPI:
    """Test cases for the /publish endpoint."""
    
    @pytest.mark.asyncio
    async def test_publish_single_event(self, http_client: httpx.AsyncClient, sample_event):
        """Test publishing a single event."""
        response = await http_client.post("/publish?sync=true", json=sample_event)
        
        assert response.status_code == 200
        result = response.json()
        
        assert result["success"] is True
        assert result["received"] == 1
        assert result["processed"] == 1
        assert sample_event["event_id"] in result["event_ids"]
    
    @pytest.mark.asyncio
    async def test_publish_batch_events(self, http_client: httpx.AsyncClient, sample_event_factory):
        """Test publishing a batch of events."""
        events = [sample_event_factory() for _ in range(5)]
        
        response = await http_client.post(
            "/publish?sync=true",
            json={"events": events}
        )
        
        assert response.status_code == 200
        result = response.json()
        
        assert result["success"] is True
        assert result["received"] == 5
        assert result["processed"] == 5
        assert result["duplicates"] == 0
    
    @pytest.mark.asyncio
    async def test_publish_invalid_event_missing_topic(self, http_client: httpx.AsyncClient):
        """Test that missing required fields are rejected."""
        invalid_event = {
            "event_id": str(uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "test",
            "payload": {}
            # Missing 'topic'
        }
        
        response = await http_client.post("/publish?sync=true", json=invalid_event)
        assert response.status_code == 422  # Validation error
    
    @pytest.mark.asyncio
    async def test_publish_invalid_event_empty_event_id(self, http_client: httpx.AsyncClient):
        """Test that empty event_id is rejected."""
        invalid_event = {
            "topic": "test.topic",
            "event_id": "",  # Empty not allowed
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "test",
            "payload": {}
        }
        
        response = await http_client.post("/publish?sync=true", json=invalid_event)
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_publish_invalid_timestamp(self, http_client: httpx.AsyncClient):
        """Test that invalid timestamp format is rejected."""
        invalid_event = {
            "topic": "test.topic",
            "event_id": str(uuid4()),
            "timestamp": "not-a-timestamp",
            "source": "test",
            "payload": {}
        }
        
        response = await http_client.post("/publish?sync=true", json=invalid_event)
        assert response.status_code == 422


class TestEventsAPI:
    """Test cases for the /events endpoint."""
    
    @pytest.mark.asyncio
    async def test_get_events_empty_topic(self, http_client: httpx.AsyncClient):
        """Test getting events from a topic with no events."""
        unique_topic = f"test.empty.{uuid4().hex[:8]}"
        
        response = await http_client.get(f"/events?topic={unique_topic}")
        
        assert response.status_code == 200
        result = response.json()
        
        assert result["events"] == []
        assert result["total"] == 0
        assert result["topic"] == unique_topic
    
    @pytest.mark.asyncio
    async def test_get_events_with_topic_filter(
        self, http_client: httpx.AsyncClient, sample_event_factory
    ):
        """Test getting events filtered by topic."""
        topic = f"test.filter.{uuid4().hex[:8]}"
        
        # Publish some events to this topic
        events = [sample_event_factory(topic=topic) for _ in range(3)]
        await http_client.post("/publish?sync=true", json={"events": events})
        
        # Get events for this topic
        response = await http_client.get(f"/events?topic={topic}")
        
        assert response.status_code == 200
        result = response.json()
        
        assert len(result["events"]) == 3
        assert result["total"] == 3
        
        # All events should be from the correct topic
        for event in result["events"]:
            assert event["topic"] == topic
    
    @pytest.mark.asyncio
    async def test_get_events_pagination(
        self, http_client: httpx.AsyncClient, sample_event_factory
    ):
        """Test pagination of events."""
        topic = f"test.pagination.{uuid4().hex[:8]}"
        
        # Publish 10 events
        events = [sample_event_factory(topic=topic) for _ in range(10)]
        await http_client.post("/publish?sync=true", json={"events": events})
        
        # Get first page (5 events)
        response = await http_client.get(f"/events?topic={topic}&limit=5&offset=0")
        assert response.status_code == 200
        result = response.json()
        assert len(result["events"]) == 5
        assert result["total"] == 10
        
        # Get second page
        response = await http_client.get(f"/events?topic={topic}&limit=5&offset=5")
        assert response.status_code == 200
        result = response.json()
        assert len(result["events"]) == 5


class TestStatsAPI:
    """Test cases for the /stats endpoint."""
    
    @pytest.mark.asyncio
    async def test_get_stats(self, http_client: httpx.AsyncClient):
        """Test getting statistics."""
        response = await http_client.get("/stats")
        
        assert response.status_code == 200
        result = response.json()
        
        # Verify all required fields are present
        assert "received" in result
        assert "unique_processed" in result
        assert "duplicate_dropped" in result
        assert "duplicate_rate" in result
        assert "topics" in result
        assert "topic_count" in result
        assert "uptime_seconds" in result
        assert "started_at" in result
    
    @pytest.mark.asyncio
    async def test_stats_update_after_publish(
        self, http_client: httpx.AsyncClient, sample_event_factory
    ):
        """Test that stats are updated after publishing."""
        stats_before = (await http_client.get("/stats")).json()
        
        # Publish an event
        event = sample_event_factory()
        await http_client.post("/publish?sync=true", json=event)
        
        stats_after = (await http_client.get("/stats")).json()
        
        # received and unique_processed should increase by 1
        assert stats_after["received"] == stats_before["received"] + 1
        assert stats_after["unique_processed"] == stats_before["unique_processed"] + 1


class TestHealthAPI:
    """Test cases for the /health endpoint."""
    
    @pytest.mark.asyncio
    async def test_health_check(self, http_client: httpx.AsyncClient):
        """Test health check endpoint."""
        response = await http_client.get("/health")
        
        assert response.status_code == 200
        result = response.json()
        
        assert result["status"] == "healthy"
        assert result["database"] == "connected"
        assert result["redis"] == "connected"
        assert "version" in result
        assert "uptime_seconds" in result


class TestRootAPI:
    """Test cases for the root endpoint."""
    
    @pytest.mark.asyncio
    async def test_root_endpoint(self, http_client: httpx.AsyncClient):
        """Test root endpoint returns basic info."""
        response = await http_client.get("/")
        
        assert response.status_code == 200
        result = response.json()
        
        assert "name" in result
        assert "version" in result
        assert "docs" in result
