# GTFS Mikroservis

[![CI](https://github.com/jatuns/gtfs-service/actions/workflows/ci.yml/badge.svg)](https://github.com/jatuns/gtfs-service/actions/workflows/ci.yml)

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

### Adım 3 — Sorgu Endpoint'leri ✅
- `app/routers/query_router.py` eklendi
- Aktif snapshot (`is_active=True`) otomatik seçilir
- `GET /routes/{route_id}/stops?direction_id=&tenant_id=burulas`
  - Hattın sıralı durakları (sample trip'in stop_sequence dizisi)
- `GET /routes/{route_id}/trips?direction_id=&service_id=&limit=&tenant_id=burulas`
  - Hattın seferleri, her sefer için ilk durağın kalkış saati (start_time)
- `GET /stops/{stop_id}/arrivals?from_time=&to_time=&route_id=&limit=&tenant_id=burulas`
  - Durağa varış saatleri, hat/zaman filtreli

### Adım 4 — Takvim Farkındalığı (date filtresi) ✅
- `calendars` tablosu artık sorgularda kullanılıyor
- `/routes/{route_id}/trips?date=YYYY-MM-DD` — o gün çalışan seferler
- `/stops/{stop_id}/arrivals?date=YYYY-MM-DD` — o güne ait varışlar
- **Yeni:** `GET /stops/{stop_id}/next?count=10&route_id=` — şu andan (Europe/Istanbul)
  itibaren bir sonraki N varış. "Bir sonraki otobüs ne zaman?" sorusunun cevabı.
- `_active_service_ids()` helper'ı: tarih → haftanın günü → çalışan service_id'ler
- Şimdilik `calendar_dates.txt` (istisna günler) desteklenmiyor — ileride eklenecek

### Adım 5 — Konum Sorgusu ✅
- `GET /stops/nearby?lat=&lon=&radius_m=&limit=` — yakındaki duraklar
- Haversine formülü SQL içinde (subquery + ORDER BY distance_m)
- `radius_m` 1..10.000 m, `limit` 1..200
- Cevapta her durak için `distance_m` (metre, 0.1 hassasiyet)
- (İleride) PostGIS + ST_DWithin + GiST index ile hızlandırılabilir

### Adım 6 — Arama & Sefer Detayı ✅
- `GET /routes/search?q=&limit=` — hat numarası / adı / route_id'de ILIKE araması
- `GET /stops/search?q=&limit=` — durak adı / stop_id'de ILIKE araması
- `GET /trips/{trip_id}` — tek seferin tam detayı:
  - Trip meta + Route bilgisi (short/long name)
  - Sıralı durak listesi (arrival/departure + sequence + pickup/drop_off)
  - Türetilen `start_time`, `end_time`, `stop_count`
- ILIKE = büyük/küçük harf duyarsız; Türkçe karakter normalizasyonu yok
  (ileride `unaccent` extension veya icu collation ile çözülür)

### Adım 7 — Performans Index'leri ✅
- Yeni composite index'ler (modelde + manuel SQL):
  - `stop_times(snapshot_id, stop_id, arrival_time)` → `/arrivals`, `/next` için
  - `trips(snapshot_id, service_id)` → date filtreli sorgular için
  - `stops(snapshot_id, stop_name)` → `/stops/search` için
  - `routes(snapshot_id, route_short_name)` → `/routes/search` için
- Mevcut DB'ye uygulamak için: `scripts/create_indexes.sql`
  ```bash
  docker exec -i gtfs_postgres psql -U gtfs_user -d gtfs_db \
    < scripts/create_indexes.sql
  ```
- Modele de eklendi (`Index(...)` __table_args__'a) — yeni tenant'larda otomatik

### Adım 8 — Pytest Smoke Testleri ✅
- `tests/` klasörü, 4 dosya, ~30 test
- Gerçek DB'ye karşı çalışıyor (mock yok — Burulas Nisan 2026 verisi)
- `conftest.py` → `client`, `known_stop`, `known_route`, `known_date` fixture'ları
- Test grupları:
  - `test_health.py` → /health
  - `test_routes.py` → /routes/{id}/stops, /trips, /search
  - `test_stops.py` → /arrivals, /next, /nearby, /search
  - `test_trips.py` → /trips/{id}
- Çalıştırma:
  ```bash
  pip install -r requirements-dev.txt
  pytest -v
  ```
- Kontroller: 200/404/422 kodları, sıralama, yarıçap/saat aralığı doğrulama,
  yetim durakların boş cevabı, türetilen alanların tutarlılığı

### Adım 9 — Pydantic Response Modelleri ✅
- `app/schemas/query.py` → 8 endpoint için tipli response sınıfları
- Ortak nested tipler tek yerden: `StopBrief`, `RouteBrief`, `ArrivalEntry`,
  `TripBrief`, `RouteStopEntry`, `TripStopEntry`, `StopWithDistance`, ...
- Her endpoint dekoratöründe `response_model=...` → FastAPI otomatik
  serileştirip doğruluyor
- Swagger UI'da artık her endpoint için tam JSON şeması + alan açıklamaları
- Hâlâ 35/35 test yeşil — cevap formatı değişmedi

### Adım 10 — GitHub Actions CI ✅
- `.github/workflows/ci.yml` her push ve PR'da koşar
- Adımlar:
  1. PostgreSQL 16 service container
  2. Python 3.12 + pip cache
  3. Bağımlılık kurulumu (`requirements-dev.txt`)
  4. Sentaks kontrolü (`python -m compileall`)
  5. Import kontrolü (`from app.main import app`)
  6. Smoke test (`pytest tests/test_health.py`)
- README'de yeşil/kırmızı rozet
- Şu an Burulas verisine bağımlı 34 test CI'da skip — sonraki iş:
  sentetik fixture GTFS ile tam test setini CI'a aç

### Adım 11 — Leaflet Frontend Demo ✅
- `app/static/demo.html` — tek HTML, vanilla JS, Leaflet CDN
- `/demo` endpoint'i ile tarayıcıdan açılır
- Etkileşim:
  - Haritaya tıkla → `/stops/nearby` (500m yarıçap, 15 durak)
  - Marker'a tıkla → `/stops/{id}/arrivals` (popup'ta varış saatleri)
- Demo Nisan verisi için sabit filtre (`date=2026-04-15`, 08:00–20:00)
  çünkü gerçek "şu an" Haziran → veri dışında
- XSS koruması: `escapeHtml` ile tüm dinamik içerik kaçırılıyor
- `/static/*` mount edildi, ileride css/img/js eklenebilir

### Adım 12 — `calendar_dates.txt` desteği ✅
- Yeni model `CalendarDate(snapshot_id, tenant_id, service_id, date, exception_type)`
- Parser opsiyonel `calendar_dates.txt`'i de okur (yoksa atlar)
- `_active_service_ids()` artık iki kaynaktan birleşim:
  - `calendars` (haftalık tarife) → BASE
  - `calendar_dates` `exception_type=1` → EKLE
  - `calendar_dates` `exception_type=2` → ÇIKAR
  - Sonuç: `(base ∪ added) − removed`
- 5 yeni izole birim test (`tests/test_active_services.py`):
  - Geçici snapshot + sentetik calendar/calendar_dates fixture
  - Normal gün, ekleme, çıkarma, başka tarih etkilenmedi mi, tarih aralığı dışı
- Index: `calendar_dates(snapshot_id, date)`
- Toplam test sayısı 35 → **40**

Not: Burulas Nisan 2026 snapshot'ı `calendar_dates.txt` içeriyor olabilir
(zip'te kontrol edin). Mevcut snapshot_id=1 bu özellik öncesinde import
edildi; calendar_dates verisi yok. Yeni özelliği tam test etmek için
veriyi yeniden import edebilirsiniz (POST /import/).

## Bitiş — Şimdilik tamam ✅
GTFS mikroservis temel hâli production-ready:
- 8 sorgu endpoint'i + import + health + demo
- 40 test, CI yeşil
- Pydantic şemalı Swagger
- Composite index'ler ile sub-ms sorgular
- Leaflet ile interaktif harita demo

### İleride yapılabilir
- CI'da sentetik fixture GTFS → tüm 40 test otomatik koşsun
- pg_trgm GIN index ile ILIKE araması daha hızlı
- Snapshot yönetimi (list/activate/delete) — Mayıs verisi gelince
- PostGIS + ST_DWithin ile nearby sub-millisaniye
- Rate limiting + API key (prod için)

## API'yi Hızlıca Test Et

### Swagger UI
http://localhost:8000/docs — tarayıcıdan endpoint'leri keşfet ve dene.

### Postman Collection
Hazır bir Postman koleksiyonu (8 endpoint + 15+ assertion + `local` environment):

🔗 **[Postman'de aç](https://baris-s-team-2.postman.co/workspace/Team-Workspace~9c8f783f-8057-45ff-8ac3-9bc933b9dbe4/collection/47917517-f489af6d-cd52-42fd-a103-0f99e8226ea7?action=share&source=copy-link&creator=47917517)**

Kullanım: Linke tıkla → "Fork this collection" → kendi workspace'ine kopya al →
sağ üst dropdown'dan `local` environment'ı seç → istekleri **Send** ile koş.
**Runner** ile collection'ın tamamını tek tıkla smoke-test edebilirsin.

## Kurulum — İki Yol

### Yol 1: venv (saf Python, hızlı)
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
```

### Yol 2: conda (scientific paketler, ileride PostGIS/ML için)
```bash
conda env create -f environment.yml
conda activate gtfs
```

İkisi de aynı testleri geçirir. Geçerli durum saf Python olduğundan venv yeterli;
geospatial/ML paketler eklendiğinde conda öne çıkar.

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