"""
Stress/Performance Tests

These tests verify the system can handle high load:
1. Process 20,000+ events with 30%+ duplicates
2. Measure throughput and latency
3. Verify correctness under load
"""
import asyncio
import time
import pytest
import httpx
from uuid import uuid4
from datetime import datetime, timezone
import random


pytestmark = [pytest.mark.integration, pytest.mark.slow]


def generate_events_with_duplicates(count: int, duplicate_rate: float) -> list:
    """Generate events with intentional duplicates."""
    unique_count = int(count * (1 - duplicate_rate))
    duplicate_count = count - unique_count
    
    unique_events = []
    for _ in range(unique_count):
        unique_events.append({
            "topic": f"stress.test.{random.choice(['alpha', 'beta', 'gamma', 'delta'])}",
            "event_id": str(uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "stress-test",
            "payload": {"data": uuid4().hex}
        })
    
    # Create duplicates
    duplicates = []
    for _ in range(duplicate_count):
        original = random.choice(unique_events)
        duplicates.append({
            "topic": original["topic"],
            "event_id": original["event_id"],
            "timestamp": original["timestamp"],
            "source": "stress-test-dup",
            "payload": original["payload"]
        })
    
    all_events = unique_events + duplicates
    random.shuffle(all_events)
    return all_events, unique_count, duplicate_count


class TestStress:
    """Stress/performance test cases."""
    
    @pytest.mark.asyncio
    async def test_process_20k_events(self, http_client: httpx.AsyncClient):
        """
        Test processing 20,000+ events with 35% duplicates.
        
        This is the minimum performance requirement from the spec.
        """
        total_events = 20000
        duplicate_rate = 0.35
        batch_size = 100
        
        events, expected_unique, expected_dupes = generate_events_with_duplicates(
            total_events, duplicate_rate
        )
        
        # Get initial stats
        stats_before = (await http_client.get("/stats")).json()
        initial_unique = stats_before.get("unique_processed", 0)
        initial_dupes = stats_before.get("duplicate_dropped", 0)
        
        start_time = time.time()
        total_processed = 0
        total_duplicates = 0
        
        # Send in batches
        for i in range(0, len(events), batch_size):
            batch = events[i:i + batch_size]
            
            response = await http_client.post(
                "/publish?sync=true",
                json={"events": batch},
                timeout=60.0
            )
            
            assert response.status_code == 200
            result = response.json()
            total_processed += result.get("processed", 0)
            total_duplicates += result.get("duplicates", 0)
        
        elapsed = time.time() - start_time
        throughput = total_events / elapsed
        
        # Verify results
        stats_after = (await http_client.get("/stats")).json()
        unique_diff = stats_after["unique_processed"] - initial_unique
        dupe_diff = stats_after["duplicate_dropped"] - initial_dupes
        
        print(f"\n{'='*60}")
        print(f"Stress Test Results:")
        print(f"  Total Events: {total_events}")
        print(f"  Expected Unique: {expected_unique}")
        print(f"  Expected Duplicates: {expected_dupes}")
        print(f"  Actual Unique Processed: {unique_diff}")
        print(f"  Actual Duplicates Dropped: {dupe_diff}")
        print(f"  Elapsed Time: {elapsed:.2f}s")
        print(f"  Throughput: {throughput:.2f} events/sec")
        print(f"{'='*60}\n")
        
        # Assertions
        assert unique_diff == expected_unique, \
            f"Expected {expected_unique} unique, got {unique_diff}"
        assert dupe_diff == expected_dupes, \
            f"Expected {expected_dupes} duplicates, got {dupe_diff}"
        
        # Performance assertion - should process at least 100 events/sec
        assert throughput >= 100, \
            f"Throughput {throughput:.2f} events/sec below minimum (100)"
    
    @pytest.mark.asyncio
    async def test_concurrent_batch_stress(self, http_client: httpx.AsyncClient):
        """
        Test high concurrency with multiple parallel batch submissions.
        """
        num_batches = 50
        batch_size = 100
        
        async def create_and_send_batch(batch_id: int):
            events = [
                {
                    "topic": f"stress.concurrent.{batch_id % 5}",
                    "event_id": str(uuid4()),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": f"batch-{batch_id}",
                    "payload": {"batch_id": batch_id}
                }
                for _ in range(batch_size)
            ]
            
            async with httpx.AsyncClient(
                base_url="http://localhost:8080",
                timeout=60.0
            ) as client:
                response = await client.post(
                    "/publish?sync=true",
                    json={"events": events}
                )
                return response.json()
        
        start_time = time.time()
        
        # Send all batches concurrently
        tasks = [create_and_send_batch(i) for i in range(num_batches)]
        results = await asyncio.gather(*tasks)
        
        elapsed = time.time() - start_time
        
        total_processed = sum(r.get("processed", 0) for r in results)
        total_events = num_batches * batch_size
        throughput = total_events / elapsed
        
        print(f"\n{'='*60}")
        print(f"Concurrent Batch Stress Test:")
        print(f"  Batches: {num_batches}")
        print(f"  Events per batch: {batch_size}")
        print(f"  Total Events: {total_events}")
        print(f"  Total Processed: {total_processed}")
        print(f"  Elapsed Time: {elapsed:.2f}s")
        print(f"  Throughput: {throughput:.2f} events/sec")
        print(f"{'='*60}\n")
        
        # All should be processed (all unique)
        assert total_processed == total_events
    
    @pytest.mark.asyncio
    async def test_latency_measurement(
        self, http_client: httpx.AsyncClient, sample_event_factory
    ):
        """
        Measure latency for single event publishing.
        """
        latencies = []
        
        for _ in range(100):
            event = sample_event_factory()
            
            start = time.time()
            response = await http_client.post("/publish?sync=true", json=event)
            elapsed = (time.time() - start) * 1000  # ms
            
            assert response.status_code == 200
            latencies.append(elapsed)
        
        avg_latency = sum(latencies) / len(latencies)
        min_latency = min(latencies)
        max_latency = max(latencies)
        
        # Calculate percentiles
        sorted_latencies = sorted(latencies)
        p50 = sorted_latencies[50]
        p95 = sorted_latencies[95]
        p99 = sorted_latencies[99]
        
        print(f"\n{'='*60}")
        print(f"Latency Test Results (100 events):")
        print(f"  Average: {avg_latency:.2f}ms")
        print(f"  Min: {min_latency:.2f}ms")
        print(f"  Max: {max_latency:.2f}ms")
        print(f"  P50: {p50:.2f}ms")
        print(f"  P95: {p95:.2f}ms")
        print(f"  P99: {p99:.2f}ms")
        print(f"{'='*60}\n")
        
        # Latency should be reasonable (< 500ms for p99)
        assert p99 < 500, f"P99 latency {p99:.2f}ms exceeds 500ms"
