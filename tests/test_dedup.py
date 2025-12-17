"""
Deduplication Tests

These tests verify the idempotent consumer and deduplication behavior:
1. Single duplicate events are correctly dropped
2. Batch duplicates are handled correctly
3. Cross-topic duplicates (same event_id, different topic) are NOT dropped
4. Dedup status is correctly reported in stats
"""
import asyncio
import pytest
import httpx
from uuid import uuid4
from datetime import datetime, timezone


pytestmark = pytest.mark.integration


class TestDeduplication:
    """Test cases for deduplication functionality."""
    
    @pytest.mark.asyncio
    async def test_single_duplicate_dropped(self, http_client: httpx.AsyncClient, sample_event_factory):
        """
        Test that sending the same event twice results in only one processed.
        
        This is the core idempotency test - the same (topic, event_id) pair
        should only be stored once.
        """
        # Create a unique event
        event = sample_event_factory(topic="test.dedup.single")
        
        # Get initial stats
        stats_before = (await http_client.get("/stats")).json()
        initial_unique = stats_before.get("unique_processed", 0)
        initial_dupes = stats_before.get("duplicate_dropped", 0)
        
        # Send the event first time
        response1 = await http_client.post("/publish?sync=true", json=event)
        assert response1.status_code == 200
        result1 = response1.json()
        assert result1["processed"] == 1
        assert result1["duplicates"] == 0
        
        # Send the same event again
        response2 = await http_client.post("/publish?sync=true", json=event)
        assert response2.status_code == 200
        result2 = response2.json()
        assert result2["processed"] == 0
        assert result2["duplicates"] == 1
        
        # Verify stats
        stats_after = (await http_client.get("/stats")).json()
        assert stats_after["unique_processed"] == initial_unique + 1
        assert stats_after["duplicate_dropped"] == initial_dupes + 1
    
    @pytest.mark.asyncio
    async def test_batch_duplicates_handled(self, http_client: httpx.AsyncClient, duplicate_events):
        """
        Test that batch publishing correctly identifies duplicates within the batch.
        
        The duplicate_events fixture contains 8 events: 5 unique, 3 duplicates.
        """
        # Send batch
        response = await http_client.post(
            "/publish?sync=true",
            json={"events": duplicate_events}
        )
        
        assert response.status_code == 200
        result = response.json()
        
        # Should process 5 unique, drop 3 duplicates
        assert result["processed"] == 5
        assert result["duplicates"] == 3
        assert result["received"] == 8
    
    @pytest.mark.asyncio
    async def test_same_event_id_different_topic_not_duplicate(
        self, http_client: httpx.AsyncClient, sample_event_factory
    ):
        """
        Test that same event_id with different topic is NOT a duplicate.
        
        Deduplication is based on (topic, event_id) pair, not event_id alone.
        """
        shared_event_id = str(uuid4())
        
        event1 = sample_event_factory(topic="test.topic.alpha", event_id=shared_event_id)
        event2 = sample_event_factory(topic="test.topic.beta", event_id=shared_event_id)
        
        # Send first event
        response1 = await http_client.post("/publish?sync=true", json=event1)
        assert response1.status_code == 200
        assert response1.json()["processed"] == 1
        
        # Send second event with same event_id but different topic
        response2 = await http_client.post("/publish?sync=true", json=event2)
        assert response2.status_code == 200
        assert response2.json()["processed"] == 1  # Should NOT be duplicate
    
    @pytest.mark.asyncio
    async def test_multiple_sends_same_event(self, http_client: httpx.AsyncClient, sample_event_factory):
        """
        Test sending the same event many times - only first should succeed.
        
        This simulates at-least-once delivery where the same message
        might be received multiple times.
        """
        event = sample_event_factory(topic="test.dedup.multiple")
        
        # Send 10 times
        results = []
        for _ in range(10):
            response = await http_client.post("/publish?sync=true", json=event)
            assert response.status_code == 200
            results.append(response.json())
        
        # First should process, rest should be duplicates
        assert results[0]["processed"] == 1
        assert results[0]["duplicates"] == 0
        
        for result in results[1:]:
            assert result["processed"] == 0
            assert result["duplicates"] == 1
    
    @pytest.mark.asyncio
    async def test_dedup_reflected_in_stats(self, http_client: httpx.AsyncClient, sample_event_factory):
        """
        Test that duplicate_rate in stats is calculated correctly.
        """
        # Create unique topic for isolation
        topic = f"test.dedup.stats.{uuid4().hex[:8]}"
        
        # Get stats before
        stats_before = (await http_client.get("/stats")).json()
        
        # Send 10 events: 5 unique, 5 duplicates of the first one
        unique_event = sample_event_factory(topic=topic)
        events = [unique_event]
        
        for _ in range(4):
            events.append(sample_event_factory(topic=topic))
        
        # Add 5 duplicates of the first event
        for _ in range(5):
            events.append(sample_event_factory(topic=topic, event_id=unique_event["event_id"]))
        
        response = await http_client.post("/publish?sync=true", json={"events": events})
        assert response.status_code == 200
        result = response.json()
        
        assert result["received"] == 10
        assert result["processed"] == 5
        assert result["duplicates"] == 5
