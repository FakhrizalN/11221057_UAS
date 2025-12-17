# Pub-Sub Log Aggregator Terdistribusi

**UAS Sistem Terdistribusi - 11221057**

Sistem Pub-Sub log aggregator multi-service dengan idempotent consumer, deduplication, dan transaksi/kontrol konkurensi menggunakan Docker Compose.

## 📋 Daftar Isi

- [Arsitektur](#arsitektur)
- [Quick Start](#quick-start)
- [API Endpoints](#api-endpoints)
- [Testing](#testing)
- [Konfigurasi](#konfigurasi)
- [Keputusan Desain](#keputusan-desain)

---

## 🏗️ Arsitektur

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose Network                    │
│                                                              │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐ │
│  │   Publisher  │────▶│    Broker    │◀────│  Aggregator  │ │
│  │   (Python)   │     │   (Redis)    │     │  (FastAPI)   │ │
│  └──────────────┘     └──────────────┘     └──────┬───────┘ │
│                                                    │         │
│                                             ┌──────▼───────┐ │
│                                             │   Storage    │ │
│                                             │ (PostgreSQL) │ │
│                                             └──────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ :8080
                    ┌──────────────────┐
                    │  Client / Demo   │
                    └──────────────────┘
```

### Komponen

| Service | Image | Deskripsi |
|---------|-------|-----------|
| **aggregator** | Python FastAPI | API endpoint, consumer workers, dedup logic |
| **publisher** | Python | Event generator dengan duplikasi |
| **broker** | `redis:7-alpine` | Message queue (Pub/Sub) |
| **storage** | `postgres:16-alpine` | Persistent dedup store + event storage |

---

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Git

### Menjalankan Sistem

```bash
# Clone repository
git clone <repository-url>
cd 11221057_UAS

# Build dan jalankan semua services
docker compose up --build -d

# Cek status
docker compose ps

# Lihat logs
docker compose logs -f aggregator
```

### Menjalankan Publisher (Event Generator)

```bash
# Jalankan publisher untuk generate 25,000 events dengan 35% duplikasi
docker compose --profile publisher up publisher
```

### Mengakses API

- **API Docs (Swagger)**: http://localhost:8080/docs
- **Health Check**: http://localhost:8080/health
- **Statistics**: http://localhost:8080/stats

### Menghentikan Sistem

```bash
# Stop semua containers (data tetap tersimpan di volumes)
docker compose down

# Stop dan hapus volumes (hapus semua data)
docker compose down -v
```

---

## 📡 API Endpoints

### POST /publish

Publish event(s) ke aggregator.

**Request Body (Single Event):**
```json
{
  "topic": "app.users.login",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-15T10:30:00Z",
  "source": "auth-service",
  "payload": {
    "user_id": "123",
    "ip_address": "192.168.1.1"
  }
}
```

**Request Body (Batch):**
```json
{
  "events": [
    { "topic": "...", "event_id": "...", ... },
    { "topic": "...", "event_id": "...", ... }
  ]
}
```

**Query Parameters:**
- `sync=true`: Process synchronously (default: false, via queue)

**Response:**
```json
{
  "success": true,
  "message": "Processed 5 events, 2 duplicates dropped",
  "received": 7,
  "processed": 5,
  "duplicates": 2,
  "event_ids": ["..."]
}
```

### GET /events

Retrieve processed events.

**Query Parameters:**
- `topic`: Filter by topic (optional)
- `limit`: Max events to return (default: 100, max: 1000)
- `offset`: Pagination offset (default: 0)

**Response:**
```json
{
  "events": [
    {
      "topic": "app.users.login",
      "event_id": "...",
      "timestamp": "2024-01-15T10:30:00Z",
      "source": "auth-service",
      "payload": {...},
      "processed_at": "2024-01-15T10:30:01Z"
    }
  ],
  "total": 1500,
  "topic": "app.users.login"
}
```

### GET /stats

Get aggregation statistics.

**Response:**
```json
{
  "received": 25000,
  "unique_processed": 16250,
  "duplicate_dropped": 8750,
  "duplicate_rate": 35.0,
  "topics": [
    {"topic": "app.users.login", "event_count": 3500},
    {"topic": "app.orders.created", "event_count": 2800}
  ],
  "topic_count": 10,
  "uptime_seconds": 3600.5,
  "started_at": "2024-01-15T10:00:00Z",
  "last_updated_at": "2024-01-15T11:00:00Z"
}
```

### GET /health

Health check for liveness/readiness probes.

**Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "version": "1.0.0",
  "uptime_seconds": 3600.5
}
```

---

## 🧪 Testing

### Prerequisites

```bash
# Install test dependencies
pip install -r tests/requirements.txt
```

### Running Tests

```bash
# Pastikan services berjalan
docker compose up -d

# Jalankan semua tests
pytest tests/ -v

# Jalankan test spesifik
pytest tests/test_dedup.py -v      # Deduplication tests
pytest tests/test_concurrency.py -v # Concurrency tests
pytest tests/test_api.py -v        # API tests
pytest tests/test_persistence.py -v # Persistence tests
pytest tests/test_stress.py -v     # Stress tests (slow)

# Jalankan dengan coverage
pytest tests/ --cov=aggregator --cov-report=html
```

### Test Categories

| Category | Test Count | Coverage |
|----------|------------|----------|
| Deduplication | 5 | Single, batch, cross-topic duplicates |
| Concurrency | 5 | Race conditions, multi-worker |
| API | 10 | All endpoints, validation |
| Persistence | 4 | Data survival, stats accumulation |
| Stress | 3 | 20k events, throughput, latency |

**Total: 27 tests**

---

## ⚙️ Konfigurasi

### Environment Variables

#### Aggregator

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://loguser:logpass@storage:5432/logdb` | PostgreSQL connection string |
| `REDIS_URL` | `redis://broker:6379` | Redis connection string |
| `WORKER_COUNT` | `4` | Number of consumer workers |
| `LOG_LEVEL` | `INFO` | Logging level |

#### Publisher

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://broker:6379` | Redis connection string |
| `AGGREGATOR_URL` | `http://aggregator:8080` | Aggregator API URL |
| `EVENT_COUNT` | `25000` | Number of events to generate |
| `DUPLICATE_RATE` | `0.35` | Duplicate rate (0.0 - 1.0) |
| `BATCH_SIZE` | `100` | Batch size for publishing |
| `PUBLISH_MODE` | `redis` | `redis` or `http` |

---

## 🎯 Keputusan Desain

### 1. Idempotency & Deduplication

- **Unique Constraint**: `(topic, event_id)` pair must be unique
- **ON CONFLICT DO NOTHING**: Atomic dedup using PostgreSQL upsert
- **Audit Log**: All events (including duplicates) logged for observability

### 2. Transaction & Concurrency

- **Isolation Level**: READ COMMITTED (PostgreSQL default)
- **Atomic Counters**: `UPDATE stats SET count = count + 1` prevents lost updates
- **Unique Constraint**: Database-level enforcement prevents race conditions

### 3. Persistence

- **Named Volumes**: `pg_data`, `redis_data` ensure data survives container restarts
- **PostgreSQL**: ACID-compliant storage for events and stats
- **Redis AOF**: Append-only file for broker durability

### 4. Reliability

- **At-least-once Delivery**: Publisher may retry, dedup ensures consistency
- **Health Checks**: Readiness probes for dependencies
- **Graceful Shutdown**: Workers complete current work before stopping

---

## 📁 Struktur Proyek

```
11221057_UAS/
├── aggregator/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py        # FastAPI application
│   │   ├── config.py      # Configuration
│   │   ├── models.py      # Pydantic models
│   │   ├── database.py    # PostgreSQL operations
│   │   └── consumer.py    # Redis consumer workers
│   └── scripts/
│       └── init.sql       # Database schema
├── publisher/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── __init__.py
│       └── main.py        # Event generator
├── tests/
│   ├── conftest.py
│   ├── requirements.txt
│   ├── test_api.py
│   ├── test_dedup.py
│   ├── test_concurrency.py
│   ├── test_persistence.py
│   └── test_stress.py
├── docker-compose.yml
├── README.md
└── report.md
```

---

## 🎬 Video Demo

[Link Video Demo YouTube](https://youtube.com/watch?v=YOUR_VIDEO_ID)

---

## 📚 Referensi

Tanenbaum, A. S., & Van Steen, M. (2017). *Distributed Systems: Principles and Paradigms* (3rd ed.). Pearson.

---

## 👤 Author

- **NIM**: 11221057
- **Mata Kuliah**: Sistem Terdistribusi
- **Semester**: Ganjil 2024/2025
