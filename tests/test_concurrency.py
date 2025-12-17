"""
Concurrency Tests

These tests verify that the system handles concurrent access correctly:
1. Multiple workers processing same event - only one succeeds
2. Concurrent batch submissions don't cause race conditions
3. Stats remain consistent under concurrent load
4. No deadlocks occur during high concurrency
"""
import asyncio
import pytest
import httpx
from uuid import uuid4
from datetime import datetime, timezone


pytestmark = pytest.mark.integration


class TestConcurrency:
    """Test cases for concurrent processing and race conditions."""
    
    @pytest.mark.asyncio
    async def test_concurrent_same_event_only_one_processed(
        self, http_client: httpx.AsyncClient, sample_event_factory
    ):
        """
        Test that sending the same event concurrently from multiple 
        'workers' results in exactly one successful insert.
        
        This simulates multiple consumer workers receiving the same
        message from the queue and trying to process it simultaneously.
        The unique constraint on (topic, event_id) ensures only one succeeds.
        """
        event = sample_event_factory(topic="test.concurrent.single")
        
        # Create multiple HTTP clients to simulate concurrent workers
        async def send_event():
            async with httpx.AsyncClient(
                base_url="http://localhost:8080",
                timeout=30.0
            ) as client:
                response = await client.post("/publish?sync=true", json=event)
                return response.json()
        
        # Send 10 concurrent requests
        tasks = [send_event() for _ in range(10)]
        results = await asyncio.gather(*tasks)
        
        # Count successful inserts vs duplicates
        total_processed = sum(r.get("processed", 0) for r in results)
        total_duplicates = sum(r.get("duplicates", 0) for r in results)
        
        # Exactly one should succeed, rest should be duplicates
        assert total_processed == 1, f"Expected 1 processed, got {total_processed}"
        assert total_duplicates == 9, f"Expected 9 duplicates, got {total_duplicates}"
    
    @pytest.mark.asyncio
    async def test_concurrent_batch_submissions(
        self, http_client: httpx.AsyncClient, sample_event_factory
    ):
        """
        Test that concurrent batch submissions don't cause data corruption.
        
        Submit multiple batches concurrently, each containing unique events.
        All events should be processed correctly.
        """
        topic = f"test.concurrent.batch.{uuid4().hex[:8]}"
        
        def create_batch(batch_id: int) -> list:
            return [
                sample_event_factory(topic=topic)
                for _ in range(10)
            ]
        
        async def send_batch(batch: list):
            async with httpx.AsyncClient(
                base_url="http://localhost:8080",
                timeout=30.0
            ) as client:
                response = await client.post(
                    "/publish?sync=true",
                    json={"events": batch}
                )
                return response.json()
        
        # Create 5 batches of 10 events each (50 total unique events)
        batches = [create_batch(i) for i in range(5)]
        
        # Send all batches concurrently
        tasks = [send_batch(batch) for batch in batches]
        results = await asyncio.gather(*tasks)
        
        # All should succeed since all events are unique
        total_processed = sum(r.get("processed", 0) for r in results)
        total_duplicates = sum(r.get("duplicates", 0) for r in results)
        
        assert total_processed == 50, f"Expected 50 processed, got {total_processed}"
        assert total_duplicates == 0, f"Expected 0 duplicates, got {total_duplicates}"
    
    @pytest.mark.asyncio
    async def test_concurrent_mixed_unique_and_duplicate(
        self, http_client: httpx.AsyncClient, sample_event_factory
    ):
        """
        Test concurrent submissions where some events are duplicates.
        
        This tests the atomicity of the dedup logic under concurrent load.
        """
        topic = f"test.concurrent.mixed.{uuid4().hex[:8]}"
        
        # Create 5 unique events
        unique_events = [sample_event_factory(topic=topic) for _ in range(5)]
        
        # Create batches that share some events
        batch1 = unique_events[:3]  # Events 0, 1, 2
        batch2 = unique_events[2:]  # Events 2, 3, 4 (event 2 is duplicate)
        
        async def send_batch(batch: list):
            async with httpx.AsyncClient(
                base_url="http://localhost:8080",
                timeout=30.0
            ) as client:
                response = await client.post(
                    "/publish?sync=true",
                    json={"events": batch}
                )
                return response.json()
        
        # Send both batches concurrently
        results = await asyncio.gather(send_batch(batch1), send_batch(batch2))
        
        # Total: 6 events sent, 5 unique, 1 duplicate (event 2)
        total_processed = sum(r.get("processed", 0) for r in results)
        total_duplicates = sum(r.get("duplicates", 0) for r in results)
        
        assert total_processed == 5, f"Expected 5 processed, got {total_processed}"
        assert total_duplicates == 1, f"Expected 1 duplicate, got {total_duplicates}"
    
    @pytest.mark.asyncio
    async def test_stats_consistency_under_load(
        self, http_client: httpx.AsyncClient, sample_event_factory
    ):
        """
        Test that stats counters remain consistent under concurrent load.
        
        This verifies that the atomic counter updates (count = count + 1)
        don't suffer from lost updates.
        """
        topic = f"test.concurrent.stats.{uuid4().hex[:8]}"
        
        stats_before = (await http_client.get("/stats")).json()
        initial_received = stats_before.get("received", 0)
        initial_unique = stats_before.get("unique_processed", 0)
        initial_dupes = stats_before.get("duplicate_dropped", 0)
        
        # Create 50 unique events
        events = [sample_event_factory(topic=topic) for _ in range(50)]
        
        async def send_single(event: dict):
            async with httpx.AsyncClient(
                base_url="http://localhost:8080",
                timeout=30.0
            ) as client:
                response = await client.post("/publish?sync=true", json=event)
                return response.json()
        
        # Send all events concurrently
        tasks = [send_single(e) for e in events]
        await asyncio.gather(*tasks)
        
        # Check stats consistency
        stats_after = (await http_client.get("/stats")).json()
        
        # All events should be received
        received_diff = stats_after["received"] - initial_received
        assert received_diff == 50, f"Expected 50 received, got {received_diff}"
        
        # All should be unique
        unique_diff = stats_after["unique_processed"] - initial_unique
        assert unique_diff == 50, f"Expected 50 unique, got {unique_diff}"
        
        # No duplicates
        dupe_diff = stats_after["duplicate_dropped"] - initial_dupes
        assert dupe_diff == 0, f"Expected 0 duplicates, got {dupe_diff}"
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_high_concurrency_no_deadlock(
        self, http_client: httpx.AsyncClient, sample_event_factory
    ):
        """
        Test that high concurrency doesn't cause deadlocks.
        
        Submit 100 concurrent requests and ensure all complete within timeout.
        """
        topic = f"test.concurrent.deadlock.{uuid4().hex[:8]}"
        
        async def send_event():
            event = sample_event_factory(topic=topic)
            async with httpx.AsyncClient(
                base_url="http://localhost:8080",
                timeout=30.0
            ) as client:
                response = await client.post("/publish?sync=true", json=event)
                return response.status_code
        
        # 100 concurrent requests
        tasks = [send_event() for _ in range(100)]
        
        # All should complete within 60 seconds (no deadlock)
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=60.0
        )
        
        # All should succeed
        success_count = sum(1 for r in results if r == 200)
        assert success_count == 100, f"Expected 100 successes, got {success_count}"
