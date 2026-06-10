# Sonraki Adımlar — Yol Günlüğü

> Bu dosya proje devam ederken hangi adımda kaldığımızı tutar.
> Yeni bir sohbet/session açtığında bunu okumak yeterli.

## Şu anki durum (PostGIS migration sonrası)

✅ **30 commit, CI yeşil**:
- 64 pytest + 32 Newman assertion otomatik koşuyor
- Pytest iç mantığı, Newman API kontratını doğrular
- Mini_gtfs fixture Burulas trip_id'leri ile hizalı (`15-2-32-06:25:00-1001`)
- PostGIS aktif: Stop.geom (geography), GiST index, ST_DWithin nearby

### Repo özet

```
app/
├── main.py               # FastAPI + 3 middleware + lifespan
├── database.py           # engine, SessionLocal, Base, get_db
├── models/gtfs.py        # 9 tablo (Snapshot/Route/Stop/Calendar/Trip/StopTime/Shape)
├── schemas/query.py      # 25+ Pydantic response/request modelleri
├── routers/
│   ├── import_router.py  # POST /import/ (API key korumalı)
│   └── query_router.py   # 11 sorgu endpoint'i
├── services/
│   ├── gtfs_parser.py    # zip → DB
│   └── journey_planner.py # v2: direct + 1-transfer
├── security/
│   ├── api_key.py        # verify_api_key dependency
│   ├── rate_limit.py     # IP başına sliding window
│   └── logging.py        # JSON istek log middleware
└── static/demo.html      # Leaflet harita

tests/                    # 64 pytest, conftest auto-fixture
docs/
├── postman_collection.json   # 32 assertion
├── postman_environment.json  # CI için
├── api-types.ts              # OpenAPI'den otomatik TS tipleri
└── USING_TYPES.md            # Frontend rehberi

.github/workflows/ci.yml  # Postgres + Pytest + Newman
```

### Çalışan tüm endpoint'ler

```
POST /import/                          🔒 API key
GET  /routes/{route_id}/stops
GET  /routes/{route_id}/trips          ?date=YYYY-MM-DD
GET  /routes/search                    ?q=
GET  /stops/{stop_id}/arrivals         ?date=&from_time=&to_time=
GET  /stops/{stop_id}/next
GET  /stops/nearby                     ?lat=&lon=&radius_m=
GET  /stops/search                     ?q=
GET  /trips/{trip_id}
GET  /journey                          direct + 1-transfer
GET  /health
GET  /demo                             Leaflet harita
```

## 🗺 Yol Haritası — Smooth sıra

Sırayı bozarsak **geri dönüş + rework** olur. Sebepler önceki sohbette tartışıldı.

### ✅ 1. PostGIS migration — TAMAMLANDI

- Image: `postgis/postgis:16-3.4` (volume korundu, veri kaybı YOK;
  yedek: `backups/gtfs_backup_pre_postgis.dump`)
- `Stop.geom geography(Point,4326)` + GiST index + parser otomatik doldurma
- `before_create` DDL listener → CREATE EXTENSION her create_all öncesi
- `/stops/nearby` → ST_DWithin + ST_Distance (metre, spheroid)
- `scripts/migrate_postgis.sql` idempotent migration
- 64 pytest + 32 Newman yeşil
- Not: Apple Silicon'da amd64 emülasyonu (~44ms); CI/prod native

### ⏭ 2. GTFS-Realtime   ← SIRADAKI

**Plan:**
- Yeni model `VehiclePosition(trip_id, lat, lon, geom, timestamp)`
- Background worker (apscheduler veya asyncio task): her 30 sn feed çek
- `/vehicles/nearby?lat=&lon=` (ST_DWithin sayesinde anlık)
- WebSocket `/ws/vehicles` canlı stream
- Demo'da harita üstünde kayan otobüs marker'ı
- Protocol Buffers (`gtfs-realtime-bindings` paketi)

**Burulas feed URL'i** — kullanıcıdan iste; yoksa mock feed üret.

### 3. Mini Frontend

Backend bittikten sonra. `docs/api-types.ts` zaten hazır.

**Plan:**
- Yeni klasör: `frontend/` (Vite + React veya Vue)
- `openapi-fetch` ile tipli istemci
- Leaflet harita (mevcut demo.html'i React'a port et)
- "Yakın duraklar" + "varış saatleri" + canlı vehicle marker (WebSocket)
- CORS env'ini frontend port'una göre ayarla

## Önemli komutlar

```bash
# DB başlat
docker compose up -d db

# Server (lokal)
source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Test
pytest

# Postman koleksiyonu CLI'dan
npx newman run docs/postman_collection.json -e docs/postman_environment.json

# CI durumunu izle
gh run watch

# TypeScript tipleri yenile (server çalışırken)
npx openapi-typescript@7 http://localhost:8000/openapi.json -o docs/api-types.ts
```

## Önemli sabitler

- **Tenant:** `burulas`
- **Aktif snapshot:** Burulas Nisan 2026
- **Bilinen durak:** `D0052` = ULUCAMI (40.18351, 29.06127)
- **Bilinen hat:** `15` = Armutkoy Mh. - Ring
- **Bilinen trip:** `15-2-32-06:25:00-1001`
- **Test tarihi:** `2026-04-15` (Çarşamba)
- **Bursa merkez koord:** lat=40.184, lon=29.061

## Açık sorular / bekleyenler

- [ ] Burulas GTFS-Realtime feed URL'i nedir? (Realtime adımı için)
- [ ] Snapshot yönetimi endpoint'leri (list/activate/delete) — Mayıs verisi gelince
- [ ] pg_trgm GIN index — `/stops/search` çok yavaşlarsa (şu an 2.6ms, gerek yok)
- [ ] Frontend ne ile yapılacak? (React mı Vue mu — kullanıcıya sor)
