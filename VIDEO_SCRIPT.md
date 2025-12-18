# Script Video Demo UAS Sistem Terdistribusi
## Pub-Sub Log Aggregator dengan Idempotent Consumer

**Durasi Target**: 20-25 menit  
**NIM**: 11221057

---

## BAGIAN 1: PEMBUKAAN (1-2 menit)

### Narasi:
> "Selamat datang di video demo UAS Sistem Terdistribusi. Nama saya [NAMA], NIM 11221057. Hari ini saya akan mendemonstrasikan sistem Pub-Sub Log Aggregator yang saya bangun dengan fitur idempotent consumer, deduplication, dan kontrol konkurensi menggunakan Docker Compose."

### Tampilkan:
- Slide pembuka atau README.md
- **File**: `README.md` - scroll ke bagian arsitektur

---

## BAGIAN 2: ARSITEKTUR SISTEM (2-3 menit)

### Narasi:
> "Sistem ini terdiri dari 4 komponen utama yang berjalan dalam Docker Compose:"
> 
> 1. **Aggregator** - FastAPI service yang menyediakan REST API dan consumer workers
> 2. **Publisher** - Event generator yang menghasilkan events dengan 35% duplikasi
> 3. **Broker** - Redis untuk message queue
> 4. **Storage** - PostgreSQL untuk persistent storage dengan unique constraint

### Tampilkan:
1. **File**: `docker-compose.yml` (line 1-80)
   - Highlight services: aggregator, publisher, broker, storage
   - Highlight volumes: `pg_data`, `redis_data`
   - Highlight healthchecks

2. **File**: `aggregator/scripts/init.sql` (line 1-30)
   - Highlight: `CONSTRAINT uq_topic_event_id UNIQUE(topic, event_id)`
   - Jelaskan: "Ini adalah constraint unik untuk deduplication"

---

## BAGIAN 3: BUILD DAN JALANKAN DOCKER (2-3 menit)

### Terminal Commands:

```bash
# Pindah ke direktori project
cd "D:\Tugas Sem 7\Sister\11221057_UAS"

# Lihat struktur project
dir

# Build dan jalankan semua services
docker compose up --build -d
```

### Narasi:
> "Sekarang saya akan build dan menjalankan semua services menggunakan Docker Compose."

### Tunggu sampai output menunjukkan:
```
✓ Container log-storage    Started
✓ Container log-broker     Started
✓ Container log-aggregator Started
```

### Lanjutkan:
```bash
# Cek status semua containers
docker compose ps
```

### Tampilkan output yang menunjukkan semua containers "healthy"

---

## BAGIAN 4: HEALTH CHECK DAN API (2-3 menit)

### Terminal Commands:

```bash
# Health check
curl http://localhost:8080/health
```

### Narasi:
> "Endpoint health check menunjukkan status koneksi ke database dan Redis."

### Expected Output:
```json
{"status":"healthy","database":"connected","redis":"connected","version":"1.0.0","uptime_seconds":...}
```

### Lanjutkan:
```bash
# Lihat statistik awal
curl http://localhost:8080/stats
```

### Narasi:
> "Statistik menunjukkan received, unique_processed, dan duplicate_dropped yang masih 0 karena belum ada events."

### Tampilkan:
- **Browser**: Buka `http://localhost:8080/docs` untuk Swagger UI
- Scroll dan tunjukkan endpoints: POST /publish, GET /events, GET /stats

---

## BAGIAN 5: DEMO IDEMPOTENCY & DEDUPLICATION (4-5 menit)

### Narasi:
> "Sekarang saya akan mendemonstrasikan idempotent consumer. Saya akan mengirim event yang sama 3 kali, dan sistem hanya akan memprosesnya sekali."

### Terminal Commands:

```bash
# Kirim event pertama kali
curl -X POST "http://localhost:8080/publish?sync=true" -H "Content-Type: application/json" -d "{\"topic\":\"demo.test\",\"event_id\":\"demo-event-001\",\"timestamp\":\"2024-01-15T10:00:00Z\",\"source\":\"demo\",\"payload\":{\"message\":\"Hello World\"}}"
```

### Narasi:
> "Event pertama berhasil diproses. Lihat processed=1, duplicates=0."

### Expected Output:
```json
{"success":true,"message":"Processed 1 events, 0 duplicates dropped","received":1,"duplicates":0,"processed":1,"event_ids":["demo-event-001"]}
```

### Lanjutkan:
```bash
# Kirim event yang SAMA untuk kedua kalinya
curl -X POST "http://localhost:8080/publish?sync=true" -H "Content-Type: application/json" -d "{\"topic\":\"demo.test\",\"event_id\":\"demo-event-001\",\"timestamp\":\"2024-01-15T10:00:00Z\",\"source\":\"demo\",\"payload\":{\"message\":\"Hello World\"}}"
```

### Narasi:
> "Perhatikan sekarang processed=0 dan duplicates=1. Event yang sama ditolak karena sudah ada."

### Expected Output:
```json
{"success":true,"message":"Processed 0 events, 1 duplicates dropped","received":1,"duplicates":1,"processed":0,"event_ids":["demo-event-001"]}
```

### Tampilkan Kode:
- **File**: `aggregator/app/database.py` (line 136-152)
- Highlight: `ON CONFLICT (topic, event_id) DO NOTHING`
- Narasi: "Ini adalah implementasi idempotent insert menggunakan PostgreSQL ON CONFLICT."

### Lanjutkan:
```bash
# Cek statistik setelah dedup
curl http://localhost:8080/stats
```

### Narasi:
> "Statistik menunjukkan received=2 (total diterima), unique_processed=1 (yang berhasil), duplicate_dropped=1 (yang ditolak)."

---

## BAGIAN 6: DEMO BATCH EVENTS DENGAN DUPLIKASI (2-3 menit)

### Narasi:
> "Sekarang saya akan mengirim batch 5 events dimana 2 diantaranya adalah duplikat."

### Terminal Commands:

```bash
# Batch dengan duplikat
curl -X POST "http://localhost:8080/publish?sync=true" -H "Content-Type: application/json" -d "{\"events\":[{\"topic\":\"batch.test\",\"event_id\":\"batch-001\",\"timestamp\":\"2024-01-15T11:00:00Z\",\"source\":\"demo\",\"payload\":{}},{\"topic\":\"batch.test\",\"event_id\":\"batch-002\",\"timestamp\":\"2024-01-15T11:00:01Z\",\"source\":\"demo\",\"payload\":{}},{\"topic\":\"batch.test\",\"event_id\":\"batch-003\",\"timestamp\":\"2024-01-15T11:00:02Z\",\"source\":\"demo\",\"payload\":{}},{\"topic\":\"batch.test\",\"event_id\":\"batch-001\",\"timestamp\":\"2024-01-15T11:00:03Z\",\"source\":\"demo\",\"payload\":{}},{\"topic\":\"batch.test\",\"event_id\":\"batch-002\",\"timestamp\":\"2024-01-15T11:00:04Z\",\"source\":\"demo\",\"payload\":{}}]}"
```

### Narasi:
> "Batch berisi 5 events, tapi batch-001 dan batch-002 muncul 2 kali. Sistem hanya memproses 3 unique events."

### Expected Output:
```json
{"success":true,"message":"Processed 3 events, 2 duplicates dropped","received":5,"duplicates":2,"processed":3,...}
```

---

## BAGIAN 7: PUBLISHER - 25,000 EVENTS (3-4 menit)

### Narasi:
> "Sekarang saya akan menjalankan Publisher yang akan generate 25,000 events dengan 35% duplikasi untuk menguji performa sistem."

### Terminal Commands:

```bash
# Jalankan publisher
docker compose --profile publisher up publisher
```

### Tunggu dan tunjukkan:
- Progress events: "Progress: 5000/25000 events published"
- Final summary dengan statistik

### Narasi saat menunggu:
> "Publisher menggenerate events dengan topic yang berbeda-beda seperti app.users.login, app.orders.created, dan lainnya. 35% dari events adalah duplikat untuk menguji deduplication."

### Setelah selesai:
```bash
# Cek statistik final
curl http://localhost:8080/stats
```

### Narasi:
> "Perhatikan bahwa dari 25,000+ events yang diterima, sekitar 16,000+ adalah unique dan 8,000+ adalah duplikat. Duplicate rate sekitar 35%."

---

## BAGIAN 8: DEMO KONKURENSI (2-3 menit)

### Narasi:
> "Saya akan menunjukkan bagaimana sistem menangani concurrent requests dengan aman."

### Tampilkan Kode:
- **File**: `aggregator/app/database.py` (line 155-168)
- Highlight: `UPDATE stats SET received = received + 1`
- Narasi: "Untuk mencegah lost updates, saya menggunakan atomic increment: count = count + 1"

- **File**: `aggregator/app/consumer.py` (line 130-145)
- Narasi: "4 worker berjalan parallel untuk memproses events dari Redis queue."

### Tampilkan Test:
- **File**: `tests/test_concurrency.py` (line 25-56)
- Narasi: "Test ini mengirim event yang sama dari 10 workers secara bersamaan. Hanya 1 yang berhasil insert, 9 lainnya menjadi duplicate."

---

## BAGIAN 9: DEMO PERSISTENSI (3-4 menit)

### Narasi:
> "Sekarang saya akan membuktikan bahwa data persisten meski container dihapus dan dibuat ulang."

### Terminal Commands:

```bash
# Catat statistik saat ini
curl http://localhost:8080/stats
```

### Catat angka received, unique_processed, duplicate_dropped

### Lanjutkan:
```bash
# Stop dan hapus containers (TAPI TETAP SIMPAN VOLUMES)
docker compose down

# Pastikan containers sudah stop
docker compose ps
```

### Narasi:
> "Containers sudah dihapus. Tapi data masih ada di Docker volumes."

### Lanjutkan:
```bash
# Jalankan ulang
docker compose up -d

# Tunggu sampai healthy
docker compose ps
```

### Tunggu sampai semua containers "healthy"

### Lanjutkan:
```bash
# Cek statistik - HARUS SAMA dengan sebelumnya
curl http://localhost:8080/stats
```

### Narasi:
> "Perhatikan statistiknya sama persis dengan sebelum restart! Data persisten berkat PostgreSQL volumes."

### Lanjutkan:
```bash
# Coba kirim event yang sama - harus tetap ditolak
curl -X POST "http://localhost:8080/publish?sync=true" -H "Content-Type: application/json" -d "{\"topic\":\"demo.test\",\"event_id\":\"demo-event-001\",\"timestamp\":\"2024-01-15T10:00:00Z\",\"source\":\"demo\",\"payload\":{\"message\":\"Hello World\"}}"
```

### Narasi:
> "Event demo-event-001 yang kita kirim di awal masih ditolak sebagai duplicate. Dedup store benar-benar persisten."

---

## BAGIAN 10: RUNNING TESTS (2-3 menit)

### Narasi:
> "Saya telah membuat 30 test cases untuk memverifikasi semua fungsionalitas sistem."

### Terminal Commands:

```bash
# Jalankan semua tests
python -m pytest tests/ -v
```

### Tunggu sampai selesai, tunjukkan output:
```
30 passed in 181.86s (0:03:01)
```

### Narasi:
> "Semua 30 tests lulus. Test mencakup deduplication, konkurensi, API, persistensi, dan stress test dengan 20,000 events."

### Tampilkan sekilas:
- **File**: `tests/test_dedup.py` - "Test deduplication"
- **File**: `tests/test_concurrency.py` - "Test race conditions"
- **File**: `tests/test_stress.py` - "Stress test 20K events"

---

## BAGIAN 11: KEAMANAN JARINGAN (1 menit)

### Narasi:
> "Sistem ini berjalan sepenuhnya dalam Docker network internal. Tidak ada koneksi ke layanan eksternal publik."

### Tampilkan:
- **File**: `docker-compose.yml` (line 70-75)
- Highlight: `networks: lognet`
- Narasi: "Semua services berkomunikasi melalui network internal 'lognet'. Hanya port 8080 yang di-expose untuk demo lokal."

---

## BAGIAN 12: KESIMPULAN (1-2 menit)

### Narasi:
> "Sebagai kesimpulan, sistem Pub-Sub Log Aggregator ini telah mengimplementasikan:"
>
> 1. **Idempotent Consumer** - Event dengan (topic, event_id) yang sama hanya diproses sekali
> 2. **Deduplication** - Menggunakan PostgreSQL unique constraint dengan ON CONFLICT DO NOTHING
> 3. **Transaksi ACID** - Semua operasi dalam transaction yang atomic
> 4. **Kontrol Konkurensi** - Multi-worker dengan atomic counter updates
> 5. **Persistensi** - Data aman dengan Docker named volumes
> 6. **Performa** - Mampu memproses 25,000+ events dengan throughput ~500 events/detik
>
> "Terima kasih telah menyaksikan demo ini."

### Tampilkan:
- Slide penutup atau scroll ke akhir README.md

---

## CHECKLIST SEBELUM RECORDING

- [ ] Docker Desktop running
- [ ] Fresh containers: `docker compose down -v && docker compose up --build -d`
- [ ] Terminal font size besar (mudah dibaca)
- [ ] Microphone tested
- [ ] Screen recording software ready
- [ ] Browser siap di `http://localhost:8080/docs`

---

## TIPS RECORDING

1. **Bicara dengan jelas dan tidak terlalu cepat**
2. **Pause sebentar setelah menjalankan command** untuk memberi waktu viewer membaca output
3. **Zoom in** pada bagian kode yang penting
4. **Highlight cursor** agar mudah diikuti
5. **Record dalam satu take** jika memungkinkan, atau edit dengan smooth transitions

---

## TIMESTAMPS ESTIMASI

| Bagian | Durasi | Total |
|--------|--------|-------|
| 1. Pembukaan | 1-2 min | 2 min |
| 2. Arsitektur | 2-3 min | 5 min |
| 3. Build Docker | 2-3 min | 8 min |
| 4. Health & API | 2-3 min | 11 min |
| 5. Idempotency | 4-5 min | 16 min |
| 6. Batch Events | 2-3 min | 19 min |
| 7. Publisher 25K | 3-4 min | 23 min |
| 8. Konkurensi | 2-3 min | 26 min |
| 9. Persistensi | 3-4 min | 30 min |
| 10. Tests | 2-3 min | 33 min |
| 11. Keamanan | 1 min | 34 min |
| 12. Kesimpulan | 1-2 min | 36 min |

> ⚠️ **Note**: Total di atas adalah estimasi maksimal. Untuk memenuhi batas 25 menit, bisa:
> - Skip bagian 6 (Batch Events)
> - Persingkat bagian 7 (tidak perlu menunggu full 25K)
> - Persingkat bagian 8 (hanya tunjukkan kode)
