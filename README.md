# GTFS Mikroservis

FastAPI + PostgreSQL + SQLAlchemy ile yazılmış GTFS veri servisi.

## Tamamlanan Adımlar

### Adım 1 — Proje İskeleti ✅
- Docker ile PostgreSQL kuruldu (port 5433)
- SQLAlchemy ORM modelleri yazıldı (8 tablo)
- FastAPI uygulaması ayağa kaldırıldı

### Adım 2 — GTFS Import ✅
- gtfs_parser.py ile zip → DB import
- Bulk insert ile 1.4M satır yazıldı
- POST /import/ endpoint'i çalışıyor
- Burulas 2026 Nisan verisi snapshot_id=1 olarak yüklendi

## Sıradaki Adım — Sorgu Endpoint'leri
- GET /routes/{route_id}/stops
- GET /routes/{route_id}/trips
- GET /stops/{stop_id}/arrivals

## Teknik Notlar
- Python 3.14 — psycopg[binary]==3.3.4 kullanılıyor (psycopg2 desteklemiyor)
- DB portu 5433 (5432 Mac'te dolu)
- stop_id string formatında: "D13-136-S"
- trip_id string formatında: "101-0-127-06:00:00-1026"
- tenant_id: "burulas"
- snapshot_id: 1 (aktif)

## Veri Yapısı (burulas_2026-april.zip)
- agency: 1 kayıt
- routes: 436 hat
- trips: 32.384 sefer  
- stops: 9.235 durak (stop_id string: "D13-136-S")
- stop_times: 1.420.857 kayıt
- calendar: 37 servis
- shapes: 386.410 nokta
- trip_id format: "101-0-127-06:00:00-1026"