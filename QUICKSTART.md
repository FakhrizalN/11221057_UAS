# Quick Start Guide - Pub-Sub Log Aggregator

## Prerequisites
✅ Python 3.14.2 installed
✅ Test dependencies installed (pytest, pytest-asyncio, httpx)
⚠️ Need: Docker Desktop running

---

## Step 1: Start Docker Desktop

Ensure Docker Desktop is running before proceeding.

---

## Step 2: Build and Start Services

```bash
cd "d:\Tugas Sem 7\Sister\11221057_UAS"

# Build and start all services (storage, broker, aggregator)
docker compose up --build -d

# Check status
docker compose ps

# View logs
docker compose logs -f aggregator
```

Expected output:
```
✓ Container log-storage   Started
✓ Container log-broker    Started  
✓ Container log-aggregator Started
```

---

## Step 3: Verify Services Are Running

```bash
# Health check
curl http://localhost:8080/health

# Should return:
# {"status":"healthy","database":"connected","redis":"connected",...}

# Check stats
curl http://localhost:8080/stats
```

---

## Step 4: Run Publisher (Generate 25,000 Events)

```bash
# Run publisher with profile
docker compose --profile publisher up publisher

# Watch the logs - should show:
# - Generating 25,000 events (35% duplicates)
# - Publishing to aggregator
# - Final statistics
```

---

## Step 5: Run Tests

### Option A: Run All Tests
```bash
python -m pytest tests/ -v
```

### Option B: Run Specific Test Categories
```bash
# Deduplication tests (5 tests)
python -m pytest tests/test_dedup.py -v

# Concurrency tests (5 tests)  
python -m pytest tests/test_concurrency.py -v

# API tests (10 tests)
python -m pytest tests/test_api.py -v

# Persistence tests (4 tests)
python -m pytest tests/test_persistence.py -v

# Stress tests (3 tests) - these take longer
python -m pytest tests/test_stress.py -v
```

---

## Step 6: Manual Testing

### Test Deduplication
```bash
# Send same event 3 times
curl -X POST http://localhost:8080/publish?sync=true ^
  -H "Content-Type: application/json" ^
  -d "{\"topic\":\"test\",\"event_id\":\"duplicate-test\",\"timestamp\":\"2024-01-15T10:00:00Z\",\"source\":\"demo\",\"payload\":{}}"

# Check stats - should show 1 unique, 2 duplicates
curl http://localhost:8080/stats
```

### Test Persistence
```bash
# 1. Publish events
curl -X POST http://localhost:8080/publish?sync=true ^
  -H "Content-Type: application/json" ^
  -d "{\"topic\":\"persist\",\"event_id\":\"persist-1\",\"timestamp\":\"2024-01-15T10:00:00Z\",\"source\":\"demo\",\"payload\":{}}"

# 2. Check stats
curl http://localhost:8080/stats

# 3. Stop containers (keep volumes)
docker compose down

# 4. Restart
docker compose up -d

# 5. Verify data persists
curl http://localhost:8080/stats
```

---

## Troubleshooting

### Issue: "Unable to get image postgres:16-alpine"
**Solution**: Start Docker Desktop first

### Issue: "connection refused" when testing
**Solution**: Wait for services to be healthy
```bash
docker compose ps
# All services should show "healthy" status
```

### Issue: pip command not working
**Solution**: Use `python -m pip` instead of `pip`

---

## Next Steps

1. ✅ **Test the system** - Run all tests
2. ✅ **Performance test** - Run publisher with 25,000 events
3. 🎥 **Record video demo** (≤25 menit) showing:
   - Architecture explanation
   - `docker compose up`
   - Event publishing with duplicates
   - Deduplication in action (/stats)
   - Container restart (persistence)
   - Running tests

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Basic info |
| `GET /docs` | Swagger UI |
| `GET /health` | Health check |
| `GET /stats` | Statistics |
| `GET /events?topic=...` | List events |
| `POST /publish?sync=true` | Publish events |

---

## Expected Performance

- **Throughput**: ~500 events/second
- **Latency P99**: <100ms
- **Concurrent Workers**: 4
- **Duplicate Detection**: 100% accurate
- **Data Persistence**: Survives container restart
