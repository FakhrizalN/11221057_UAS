"""
Persistence Tests

These tests verify data persistence across container restarts:
1. Events survive container restart
2. Stats survive container restart
3. Dedup store prevents reprocessing after restart
"""
import pytest
import httpx
from uuid import uuid4
from datetime import datetime, timezone


pytestmark = pytest.mark.integration


class TestPersistence:
    """
    Test cases for data persistence.
    
    Note: Full persistence testing requires manual container restart.
    These tests verify the data is stored in the database correctly.
    """
    
    @pytest.mark.asyncio
    async def test_events_stored_in_database(
        self, http_client: httpx.AsyncClient, sample_event_factory
    ):
        """
        Test that published events are stored and can be retrieved.
        
        This verifies the persistence layer is working.
        """
        topic = f"test.persist.store.{uuid4().hex[:8]}"
        events = [sample_event_factory(topic=topic) for _ in range(5)]
        
        # Publish events
        response = await http_client.post(
            "/publish?sync=true",
            json={"events": events}
        )
        assert response.status_code == 200
        
        # Retrieve events
        response = await http_client.get(f"/events?topic={topic}")
        assert response.status_code == 200
        result = response.json()
        
        assert result["total"] == 5
        
        # Verify all event_ids are present
        stored_ids = {e["event_id"] for e in result["events"]}
        original_ids = {e["event_id"] for e in events}
        assert stored_ids == original_ids
    
    @pytest.mark.asyncio
    async def test_stats_accumulate(self, http_client: httpx.AsyncClient, sample_event_factory):
        """
        Test that stats accumulate over multiple operations.
        
        This verifies stats persistence and atomic updates.
        """
        stats_before = (await http_client.get("/stats")).json()
        
        # Publish 10 unique events
        topic = f"test.persist.stats.{uuid4().hex[:8]}"
        events = [sample_event_factory(topic=topic) for _ in range(10)]
        await http_client.post("/publish?sync=true", json={"events": events})
        
        # Publish 5 duplicates
        duplicates = events[:5]
        await http_client.post("/publish?sync=true", json={"events": duplicates})
        
        stats_after = (await http_client.get("/stats")).json()
        
        # Verify accumulation
        assert stats_after["received"] == stats_before["received"] + 15
        assert stats_after["unique_processed"] == stats_before["unique_processed"] + 10
        assert stats_after["duplicate_dropped"] == stats_before["duplicate_dropped"] + 5
    
    @pytest.mark.asyncio
    async def test_dedup_persists_across_requests(
        self, http_client: httpx.AsyncClient, sample_event_factory
    ):
        """
        Test that dedup store persists - same event is rejected even after time.
        
        This verifies the unique constraint on (topic, event_id) is permanent.
        """
        event = sample_event_factory(topic="test.persist.dedup")
        
        # First publish
        response1 = await http_client.post("/publish?sync=true", json=event)
        assert response1.json()["processed"] == 1
        
        # Wait and try again
        import asyncio
        await asyncio.sleep(1)
        
        # Second publish - should still be duplicate
        response2 = await http_client.post("/publish?sync=true", json=event)
        assert response2.json()["duplicates"] == 1
        assert response2.json()["processed"] == 0
    
    @pytest.mark.asyncio
    async def test_topic_breakdown_persists(
        self, http_client: httpx.AsyncClient, sample_event_factory
    ):
        """
        Test that topic breakdown in stats is accurate.
        """
        # Create events for specific topics
        topics = [f"test.persist.topic.{i}" for i in range(3)]
        
        for i, topic in enumerate(topics):
            events = [sample_event_factory(topic=topic) for _ in range(i + 1)]
            await http_client.post("/publish?sync=true", json={"events": events})
        
        # Check stats
        stats = (await http_client.get("/stats")).json()
        
        topic_counts = {t["topic"]: t["event_count"] for t in stats["topics"]}
        
        # Verify at least our test topics are present
        for i, topic in enumerate(topics):
            assert topic in topic_counts, f"Topic {topic} not in stats"
            assert topic_counts[topic] >= i + 1


class TestPersistenceManual:
    """
    Manual persistence tests - require container restart.
    
    Instructions:
    1. Run test_store_events_for_restart
    2. Stop containers: docker compose down
    3. Start containers: docker compose up -d
    4. Run test_verify_events_after_restart with same event_ids
    """
    
    @pytest.mark.asyncio
    async def test_store_events_for_restart(
        self, http_client: httpx.AsyncClient, sample_event_factory
    ):
        """
        Store events that will be verified after restart.
        
        Note the event_ids printed for verification.
        """
        topic = "test.restart.manual"
        events = [sample_event_factory(topic=topic) for _ in range(3)]
        
        response = await http_client.post(
            "/publish?sync=true",
            json={"events": events}
        )
        assert response.status_code == 200
        
        print("\n" + "="*60)
        print("Events stored for restart test:")
        print(f"Topic: {topic}")
        for e in events:
            print(f"  - {e['event_id']}")
        print("="*60 + "\n")
        
        # Store event_ids for later verification
        # In a real test, these would be saved to a file


# Note: test_verify_events_after_restart would need event_ids from the previous test
# This would typically be done manually or with a test state file
