-- ─────────────────────────────────────────
-- PostGIS Migration — mevcut DB için
-- ─────────────────────────────────────────
-- Yeni kurulumlarda gerek yok: model + parser geom'u otomatik halleder.
-- Bu script, PostGIS ÖNCESİ import edilmiş veriye geom ekler.
--
-- Idempotent: birden fazla çalıştırılabilir.
--
-- Çalıştırma:
--   docker exec -i gtfs_postgres psql -U gtfs_user -d gtfs_db \
--     < scripts/migrate_postgis.sql

-- 1. Extension (yeni postgis/postgis image'ında paket hazır, aktive et)
CREATE EXTENSION IF NOT EXISTS postgis;

-- 2. stops tablosuna geography kolonu ekle
ALTER TABLE stops ADD COLUMN IF NOT EXISTS geom geography(Point, 4326);

-- 3. Mevcut lat/lon'dan geom üret
--    ST_MakePoint(x, y) → x=BOYLAM, y=ENLEM (ters sıra, klasik tuzak!)
UPDATE stops
SET geom = ST_SetSRID(ST_MakePoint(stop_lon, stop_lat), 4326)::geography
WHERE geom IS NULL
  AND stop_lat IS NOT NULL
  AND stop_lon IS NOT NULL;

-- 4. GiST index — ST_DWithin sorgularının hızlanma sebebi
CREATE INDEX IF NOT EXISTS idx_stops_geom ON stops USING GIST (geom);

-- 5. İstatistikleri yenile (planner GiST'i tanısın)
ANALYZE stops;

-- Kontrol
\echo
\echo '─── geom dolu satır sayısı ───'
SELECT COUNT(*) AS geom_dolu FROM stops WHERE geom IS NOT NULL;

\echo
\echo '─── stops index listesi ───'
SELECT indexname FROM pg_indexes WHERE tablename = 'stops' ORDER BY indexname;
