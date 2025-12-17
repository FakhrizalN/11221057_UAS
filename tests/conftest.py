"""
Pytest configuration and fixtures for integration tests.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import AsyncGenerator, Generator
from uuid import uuid4

import pytest
import pytest_asyncio
import httpx

# Test configuration
TEST_AGGREGATOR_URL = os.getenv("TEST_AGGREGATOR_URL", "http://localhost:8080")


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create an async HTTP client."""
    async with httpx.AsyncClient(
        base_url=TEST_AGGREGATOR_URL,
        timeout=30.0
    ) as client:
        yield client


@pytest.fixture
def sample_event() -> dict:
    """Generate a sample event for testing."""
    return {
        "topic": f"test.topic.{uuid4().hex[:8]}",
        "event_id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "test-suite",
        "payload": {
            "test_key": "test_value",
            "number": 42
        }
    }


@pytest.fixture
def sample_event_factory():
    """Factory fixture for generating multiple unique events."""
    def _factory(topic: str = None, event_id: str = None) -> dict:
        return {
            "topic": topic or f"test.topic.{uuid4().hex[:8]}",
            "event_id": event_id or str(uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "test-suite",
            "payload": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "random_id": uuid4().hex
            }
        }
    return _factory


@pytest.fixture
def duplicate_events(sample_event_factory) -> list:
    """Generate a set of events with intentional duplicates."""
    # Create 5 unique events
    unique_events = [sample_event_factory(topic="test.duplicates") for _ in range(5)]
    
    # Create duplicates of the first 3
    duplicates = [
        sample_event_factory(
            topic=unique_events[i]["topic"],
            event_id=unique_events[i]["event_id"]
        )
        for i in range(3)
    ]
    
    return unique_events + duplicates  # 8 total, 5 unique, 3 duplicates


def pytest_configure(config):
    """Add custom markers."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (require running services)"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running"
    )
