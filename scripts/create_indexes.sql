-- ─────────────────────────────────────────
-- Performans Index'leri
-- ─────────────────────────────────────────
-- Bu SQL mevcut DB'ye eklenmeyen index'leri ekler.
-- Idempotent: birden fazla çalıştırılabilir (IF NOT EXISTS).
--
-- Çalıştırma:
--   docker exec -i gtfs_postgres psql -U gtfs_user -d gtfs_db \
--     < scripts/create_indexes.sql
--
-- Süre tahmini (1.4M satırlı stop_times için):
--   ~10-30 saniye. CONCURRENTLY kullanmıyoruz çünkü:
--   - tek geliştirme ortamı, prod değil
--   - lock alınmasının zararı yok

-- /stops/{id}/arrivals ve /stops/{id}/next için kritik
-- (snapshot_id, stop_id) zaten var ama arrival_time'ı da indekslemek
-- WHERE arrival_time >= X filtresini ve ORDER BY arrival_time'ı
-- tek tarama haline getirir.
CREATE INDEX IF NOT EXISTS ix_stop_times_stop_arrival
  ON stop_times (snapshot_id, stop_id, arrival_time);

-- /routes/{id}/trips ve /arrivals?date= için
-- (snapshot_id, route_id) zaten var; service_id de calendar
-- filtresinde IN (...) ile kullanılıyor.
CREATE INDEX IF NOT EXISTS ix_trips_snapshot_service
  ON trips (snapshot_id, service_id);

-- /stops/search için (ILIKE ile sınırlı fayda ama yine de yararlı)
CREATE INDEX IF NOT EXISTS ix_stops_name
  ON stops (snapshot_id, stop_name);

-- /routes/search için
CREATE INDEX IF NOT EXISTS ix_routes_short_name
  ON routes (snapshot_id, route_short_name);

-- Kontrol: index'ler oluştu mu?
\echo
\echo '─── stop_times index listesi ───'
SELECT indexname, indexdef FROM pg_indexes
WHERE tablename = 'stop_times' ORDER BY indexname;

\echo
\echo '─── trips index listesi ───'
SELECT indexname FROM pg_indexes
WHERE tablename = 'trips' ORDER BY indexname;

\echo
\echo '─── stops index listesi ───'
SELECT indexname FROM pg_indexes
WHERE tablename = 'stops' ORDER BY indexname;

\echo
\echo '─── routes index listesi ───'
SELECT indexname FROM pg_indexes
WHERE tablename = 'routes' ORDER BY indexname;
