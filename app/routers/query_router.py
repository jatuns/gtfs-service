"""
Query Router
------------
GTFS sorgu endpoint'leri.

Tüm endpoint'ler tenant_id ile filtrelenir ve o tenant'ın
aktif (is_active=True) snapshot'ını kullanır. Böylece eski
import'lar DB'de durur ama sorgular hep güncel veriden döner.

Endpoint'ler:
  GET /routes/{route_id}/stops      → hattın sıralı durakları
  GET /routes/{route_id}/trips      → hattın seferleri (date filtresi opsiyonel)
  GET /stops/{stop_id}/arrivals     → durağa varış saatleri (date filtresi opsiyonel)
  GET /stops/{stop_id}/next         → şu andan sonraki ilk N varış (kısa yol)
  GET /stops/nearby                 → koordinata yakın duraklar (Haversine)
"""

from datetime import date as date_cls, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, literal
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.gtfs import (
    Calendar, GtfsSnapshot, Route, Stop, Trip, StopTime
)

router = APIRouter(tags=["Query"])

# GTFS calendars.txt → weekday kolon sırası (Pazartesi=0 ile uyumlu)
# datetime.weekday() Pazartesi=0, Pazar=6 döner.
_WEEKDAY_COLUMNS = [
    "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday",
]

# Burulas saat dilimi. İleride agency_timezone'dan dinamik okuyabiliriz.
_LOCAL_TZ = ZoneInfo("Europe/Istanbul")


# ─────────────────────────────────────────
# YARDIMCI — aktif snapshot'ı getir
# ─────────────────────────────────────────
def _get_active_snapshot(db: Session, tenant_id: str) -> GtfsSnapshot:
    """
    Verilen tenant için is_active=True olan snapshot'ı döndürür.
    Yoksa 404 atar.
    """
    snap = (
        db.query(GtfsSnapshot)
        .filter(GtfsSnapshot.tenant_id == tenant_id)
        .filter(GtfsSnapshot.is_active == True)  # noqa: E712
        .order_by(GtfsSnapshot.id.desc())
        .first()
    )
    if not snap:
        raise HTTPException(
            status_code=404,
            detail=f"'{tenant_id}' için aktif snapshot bulunamadı",
        )
    return snap


# ─────────────────────────────────────────
# YARDIMCI — bir tarihte çalışan service_id'leri bul
# ─────────────────────────────────────────
def _parse_date(s: str) -> date_cls:
    """
    'YYYY-MM-DD' → date.
    Geçersizse 400 atar.
    """
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            400, f"Geçersiz tarih formatı: '{s}'. Beklenen format: YYYY-MM-DD"
        )


def _active_service_ids(
    db: Session, snapshot_id: int, target_date: date_cls
) -> list[str]:
    """
    Belirtilen tarihte aktif olan service_id listesini döndürür.

    GTFS calendars.txt mantığı:
      - Bir servis 'start_date'..'end_date' aralığında geçerlidir
      - O tarihin haftanın günü kolonu (örn: monday) 1 olmalı
      - GTFS calendar_dates.txt ile istisnalar tanımlanabilir
        (özel günler, iptal günleri) — şimdilik desteklemiyoruz,
        ileride eklenebilir.

    Tarihler DB'de 'YYYYMMDD' formatında (Burulas verisi öyle gönderiyor).
    Bu format string olarak da doğru sıralanır (lexicographic ordering).
    """
    weekday_col_name = _WEEKDAY_COLUMNS[target_date.weekday()]
    weekday_col = getattr(Calendar, weekday_col_name)
    date_str = target_date.strftime("%Y%m%d")  # "20260604"

    rows = (
        db.query(Calendar.service_id)
        .filter(Calendar.snapshot_id == snapshot_id)
        .filter(weekday_col == 1)
        .filter(Calendar.start_date <= date_str)
        .filter(Calendar.end_date >= date_str)
        .all()
    )
    return [r[0] for r in rows]


def _now_local() -> datetime:
    """Yerel saat (Europe/Istanbul). Test edilebilirlik için ayrı fonksiyon."""
    return datetime.now(_LOCAL_TZ)


# ─────────────────────────────────────────
# GET /routes/{route_id}/stops
# ─────────────────────────────────────────
@router.get("/routes/{route_id}/stops")
def get_route_stops(
    route_id: str,
    direction_id: int | None = Query(
        None, description="0=gidiş, 1=dönüş. Belirtilmezse tüm yönler."
    ),
    tenant_id: str = Query("burulas"),
    db: Session = Depends(get_db),
):
    """
    Bir hattın duraklarını sıralı olarak döndürür.

    Mantık:
      1. route_id'ye ait bir trip seç (örnek olarak ilk trip yeterli,
         çünkü aynı route + direction için stop dizisi aynıdır)
      2. O trip'in stop_times kayıtlarını stop_sequence'a göre sırala
      3. Her stop_id için Stop tablosundan ad/koord bilgisini join et
    """
    snap = _get_active_snapshot(db, tenant_id)

    # 1. Hattın varlığını doğrula
    route_exists = (
        db.query(Route.id)
        .filter(Route.snapshot_id == snap.id)
        .filter(Route.route_id == route_id)
        .first()
    )
    if not route_exists:
        raise HTTPException(404, f"route_id={route_id} bulunamadı")

    # 2. Örnek bir trip seç
    trip_q = (
        db.query(Trip.trip_id)
        .filter(Trip.snapshot_id == snap.id)
        .filter(Trip.route_id == route_id)
    )
    if direction_id is not None:
        trip_q = trip_q.filter(Trip.direction_id == direction_id)

    trip_row = trip_q.first()
    if not trip_row:
        raise HTTPException(
            404,
            f"route_id={route_id} için sefer bulunamadı"
            + (f" (direction_id={direction_id})" if direction_id is not None else ""),
        )
    sample_trip_id = trip_row[0]

    # 3. O trip'in stop_times'larını Stop ile join'le, sequence'a göre sırala
    rows = (
        db.query(
            StopTime.stop_sequence,
            StopTime.arrival_time,
            StopTime.departure_time,
            Stop.stop_id,
            Stop.stop_name,
            Stop.stop_lat,
            Stop.stop_lon,
        )
        .join(
            Stop,
            (Stop.stop_id == StopTime.stop_id)
            & (Stop.snapshot_id == StopTime.snapshot_id),
        )
        .filter(StopTime.snapshot_id == snap.id)
        .filter(StopTime.trip_id == sample_trip_id)
        .order_by(StopTime.stop_sequence.asc())
        .all()
    )

    return {
        "tenant_id": tenant_id,
        "snapshot_id": snap.id,
        "route_id": route_id,
        "direction_id": direction_id,
        "sample_trip_id": sample_trip_id,
        "stop_count": len(rows),
        "stops": [
            {
                "sequence": r.stop_sequence,
                "stop_id": r.stop_id,
                "stop_name": r.stop_name,
                "stop_lat": r.stop_lat,
                "stop_lon": r.stop_lon,
                "arrival_time": r.arrival_time,
                "departure_time": r.departure_time,
            }
            for r in rows
        ],
    }


# ─────────────────────────────────────────
# GET /routes/{route_id}/trips
# ─────────────────────────────────────────
@router.get("/routes/{route_id}/trips")
def get_route_trips(
    route_id: str,
    direction_id: int | None = Query(None, description="0=gidiş, 1=dönüş"),
    service_id: str | None = Query(None, description="Belirli bir servis (gün) için filtre"),
    date: str | None = Query(
        None,
        description="YYYY-MM-DD. Verilirse o tarihte çalışan seferler döner.",
    ),
    limit: int = Query(200, ge=1, le=2000),
    tenant_id: str = Query("burulas"),
    db: Session = Depends(get_db),
):
    """
    Bir hatta ait seferleri listeler.

    Her trip için ilk durağın kalkış saatini (start_time) ekliyoruz,
    çünkü saat sırasına göre göstermek istiyoruz.

    date verilirse: o tarihin haftanın gününe göre çalışan service_id'ler
    bulunur ve sefer listesi onlara filtrelenir. service_id ile birlikte
    verilebilir — ikisi de uygulanır (AND).
    """
    snap = _get_active_snapshot(db, tenant_id)

    # date verildiyse o gün çalışan service_id'leri çek
    active_services: list[str] | None = None
    if date is not None:
        target = _parse_date(date)
        active_services = _active_service_ids(db, snap.id, target)
        if not active_services:
            # O gün hiç servis yok → boş cevap, sorgu yapmaya gerek yok
            return {
                "tenant_id": tenant_id,
                "snapshot_id": snap.id,
                "route_id": route_id,
                "direction_id": direction_id,
                "service_id": service_id,
                "date": date,
                "trip_count": 0,
                "trips": [],
            }

    # İlk durağın departure_time'ı = sefer başlangıç saati
    # stop_sequence en küçük olan stop_time
    # Burada subquery ile MIN(stop_sequence)'ı buluyoruz
    first_stop_sq = (
        db.query(
            StopTime.trip_id.label("trip_id"),
            func.min(StopTime.stop_sequence).label("min_seq"),
        )
        .filter(StopTime.snapshot_id == snap.id)
        .group_by(StopTime.trip_id)
        .subquery()
    )

    q = (
        db.query(
            Trip.trip_id,
            Trip.service_id,
            Trip.direction_id,
            Trip.shape_id,
            Trip.trip_headsign,
            StopTime.departure_time.label("start_time"),
        )
        .join(first_stop_sq, first_stop_sq.c.trip_id == Trip.trip_id)
        .join(
            StopTime,
            (StopTime.trip_id == Trip.trip_id)
            & (StopTime.snapshot_id == Trip.snapshot_id)
            & (StopTime.stop_sequence == first_stop_sq.c.min_seq),
        )
        .filter(Trip.snapshot_id == snap.id)
        .filter(Trip.route_id == route_id)
    )

    if direction_id is not None:
        q = q.filter(Trip.direction_id == direction_id)
    if service_id is not None:
        q = q.filter(Trip.service_id == service_id)
    if active_services is not None:
        q = q.filter(Trip.service_id.in_(active_services))

    rows = q.order_by(StopTime.departure_time.asc()).limit(limit).all()

    return {
        "tenant_id": tenant_id,
        "snapshot_id": snap.id,
        "route_id": route_id,
        "direction_id": direction_id,
        "service_id": service_id,
        "date": date,
        "trip_count": len(rows),
        "trips": [
            {
                "trip_id": r.trip_id,
                "service_id": r.service_id,
                "direction_id": r.direction_id,
                "shape_id": r.shape_id,
                "trip_headsign": r.trip_headsign,
                "start_time": r.start_time,
            }
            for r in rows
        ],
    }


# ─────────────────────────────────────────
# GET /stops/{stop_id}/arrivals
# ─────────────────────────────────────────
@router.get("/stops/{stop_id}/arrivals")
def get_stop_arrivals(
    stop_id: str,
    from_time: str | None = Query(
        None, description="HH:MM:SS — bu saatten itibaren (dahil)"
    ),
    to_time: str | None = Query(
        None, description="HH:MM:SS — bu saate kadar (dahil)"
    ),
    date: str | None = Query(
        None,
        description="YYYY-MM-DD. Verilirse sadece o gün çalışan seferler döner.",
    ),
    route_id: str | None = Query(None, description="Belirli hat için filtre"),
    limit: int = Query(100, ge=1, le=1000),
    tenant_id: str = Query("burulas"),
    db: Session = Depends(get_db),
):
    """
    Bir durağa varış saatlerini döndürür.

    Her satır = bir sefer × bu durak.
    Saat aralığı verilirse o aralıkta filtrelenir.

    date verilirse: o tarihin haftanın gününe uyan service_id'ler bulunur
    ve sadece o servislere ait varışlar döner. Pazartesi/Pazar farkını
    böyle ayırırız.
    """
    snap = _get_active_snapshot(db, tenant_id)

    # date verildiyse o gün çalışan service_id'leri çek
    active_services: list[str] | None = None
    if date is not None:
        target = _parse_date(date)
        active_services = _active_service_ids(db, snap.id, target)
        if not active_services:
            # O gün hiç servis yok → boş cevap
            stop_empty = (
                db.query(Stop)
                .filter(Stop.snapshot_id == snap.id)
                .filter(Stop.stop_id == stop_id)
                .first()
            )
            if not stop_empty:
                raise HTTPException(404, f"stop_id={stop_id} bulunamadı")
            return {
                "tenant_id": tenant_id,
                "snapshot_id": snap.id,
                "stop_id": stop_id,
                "stop_name": stop_empty.stop_name,
                "stop_lat": stop_empty.stop_lat,
                "stop_lon": stop_empty.stop_lon,
                "filters": {
                    "from_time": from_time,
                    "to_time": to_time,
                    "date": date,
                    "route_id": route_id,
                    "limit": limit,
                },
                "arrival_count": 0,
                "arrivals": [],
            }

    # Durağın varlığını ve adını al
    stop = (
        db.query(Stop)
        .filter(Stop.snapshot_id == snap.id)
        .filter(Stop.stop_id == stop_id)
        .first()
    )
    if not stop:
        raise HTTPException(404, f"stop_id={stop_id} bulunamadı")

    # stop_times → trips join ile hat bilgisini de getir
    q = (
        db.query(
            StopTime.arrival_time,
            StopTime.departure_time,
            StopTime.stop_sequence,
            Trip.trip_id,
            Trip.route_id,
            Trip.direction_id,
            Trip.trip_headsign,
            Trip.service_id,
        )
        .join(
            Trip,
            (Trip.trip_id == StopTime.trip_id)
            & (Trip.snapshot_id == StopTime.snapshot_id),
        )
        .filter(StopTime.snapshot_id == snap.id)
        .filter(StopTime.stop_id == stop_id)
    )

    if from_time is not None:
        q = q.filter(StopTime.arrival_time >= from_time)
    if to_time is not None:
        q = q.filter(StopTime.arrival_time <= to_time)
    if route_id is not None:
        q = q.filter(Trip.route_id == route_id)
    if active_services is not None:
        q = q.filter(Trip.service_id.in_(active_services))

    rows = q.order_by(StopTime.arrival_time.asc()).limit(limit).all()

    return {
        "tenant_id": tenant_id,
        "snapshot_id": snap.id,
        "stop_id": stop_id,
        "stop_name": stop.stop_name,
        "stop_lat": stop.stop_lat,
        "stop_lon": stop.stop_lon,
        "filters": {
            "from_time": from_time,
            "to_time": to_time,
            "date": date,
            "route_id": route_id,
            "limit": limit,
        },
        "arrival_count": len(rows),
        "arrivals": [
            {
                "arrival_time": r.arrival_time,
                "departure_time": r.departure_time,
                "trip_id": r.trip_id,
                "route_id": r.route_id,
                "direction_id": r.direction_id,
                "trip_headsign": r.trip_headsign,
                "service_id": r.service_id,
                "stop_sequence": r.stop_sequence,
            }
            for r in rows
        ],
    }


# ─────────────────────────────────────────
# GET /stops/{stop_id}/next
# Pratik kısa yol: "şu andan itibaren ilk N varış, bugün"
# ─────────────────────────────────────────
@router.get("/stops/{stop_id}/next")
def get_stop_next_arrivals(
    stop_id: str,
    count: int = Query(10, ge=1, le=50, description="Kaç tane sonraki varış"),
    route_id: str | None = Query(None, description="Belirli hat için filtre"),
    tenant_id: str = Query("burulas"),
    db: Session = Depends(get_db),
):
    """
    Şu andan (Europe/Istanbul) itibaren bu durağa gelecek ilk N varış.

    'Bir sonraki otobüs ne zaman?' sorusunun cevabı.

    Mantık:
      1. Yerel saati al → tarih + saat
      2. O tarihte çalışan service_id'leri bul (calendars)
      3. stop_times'ı: snapshot + stop + service + arrival_time >= now ile filtrele
      4. arrival_time'a göre sırala, count kadar al

    Not: GTFS arrival_time 24:00:00'ı geçebilir ("25:30:00" = ertesi gün 01:30).
    Şu an gece 01:00 olduğunda dünün servisinden gelen "25:00:00" varışları
    da görmek isteyebiliriz — şimdilik bu uç durumu atlıyoruz, basit tutuyoruz.
    """
    snap = _get_active_snapshot(db, tenant_id)

    # Durağı al
    stop = (
        db.query(Stop)
        .filter(Stop.snapshot_id == snap.id)
        .filter(Stop.stop_id == stop_id)
        .first()
    )
    if not stop:
        raise HTTPException(404, f"stop_id={stop_id} bulunamadı")

    now = _now_local()
    today = now.date()
    now_hhmmss = now.strftime("%H:%M:%S")

    active_services = _active_service_ids(db, snap.id, today)
    if not active_services:
        return {
            "tenant_id": tenant_id,
            "snapshot_id": snap.id,
            "stop_id": stop_id,
            "stop_name": stop.stop_name,
            "now_local": now.isoformat(),
            "date": today.isoformat(),
            "arrival_count": 0,
            "arrivals": [],
            "note": "Bugün için aktif servis bulunamadı (tarih takvim dışı olabilir).",
        }

    q = (
        db.query(
            StopTime.arrival_time,
            StopTime.departure_time,
            StopTime.stop_sequence,
            Trip.trip_id,
            Trip.route_id,
            Trip.direction_id,
            Trip.trip_headsign,
            Trip.service_id,
        )
        .join(
            Trip,
            (Trip.trip_id == StopTime.trip_id)
            & (Trip.snapshot_id == StopTime.snapshot_id),
        )
        .filter(StopTime.snapshot_id == snap.id)
        .filter(StopTime.stop_id == stop_id)
        .filter(Trip.service_id.in_(active_services))
        .filter(StopTime.arrival_time >= now_hhmmss)
    )
    if route_id is not None:
        q = q.filter(Trip.route_id == route_id)

    rows = q.order_by(StopTime.arrival_time.asc()).limit(count).all()

    return {
        "tenant_id": tenant_id,
        "snapshot_id": snap.id,
        "stop_id": stop_id,
        "stop_name": stop.stop_name,
        "stop_lat": stop.stop_lat,
        "stop_lon": stop.stop_lon,
        "now_local": now.isoformat(),
        "date": today.isoformat(),
        "weekday": _WEEKDAY_COLUMNS[today.weekday()],
        "active_service_count": len(active_services),
        "arrival_count": len(rows),
        "arrivals": [
            {
                "arrival_time": r.arrival_time,
                "departure_time": r.departure_time,
                "trip_id": r.trip_id,
                "route_id": r.route_id,
                "direction_id": r.direction_id,
                "trip_headsign": r.trip_headsign,
                "service_id": r.service_id,
                "stop_sequence": r.stop_sequence,
            }
            for r in rows
        ],
    }


# ─────────────────────────────────────────
# GET /stops/nearby
# Bir noktaya yakın durakları, mesafeyle birlikte döner.
# ─────────────────────────────────────────
@router.get("/stops/nearby")
def get_stops_nearby(
    lat: float = Query(..., ge=-90, le=90, description="Enlem (derece)"),
    lon: float = Query(..., ge=-180, le=180, description="Boylam (derece)"),
    radius_m: int = Query(
        500, ge=1, le=10_000,
        description="Arama yarıçapı (metre). Maks 10 km.",
    ),
    limit: int = Query(20, ge=1, le=200),
    tenant_id: str = Query("burulas"),
    db: Session = Depends(get_db),
):
    """
    Verilen (lat, lon) noktasına `radius_m` metreden yakın durakları,
    en yakından uzağa sıralı olarak döndürür.

    Mesafe Haversine formülü ile hesaplanır (Dünya = yaklaşık küre).
    Hesabı Python'da değil DB'de yapıyoruz: PostgreSQL satır taraması
    sırasında mesafeyi zaten hesaplıyor, bir kez ek matematikle filtreyi
    de aynı pass'te bitiriyor — 9k duraklık aktif snapshot için anlık.

    Formül (R = Dünya yarıçapı, metre):
        a = sin²(Δφ/2) + cos(φ1) · cos(φ2) · sin²(Δλ/2)
        d = 2 · R · asin(√a)

    SQLAlchemy notu: hesaplanan distance_m'i hem ORDER BY hem WHERE'de
    kullanmak için iki yol var:
      1) Aynı uzun ifadeyi iki yere de yazmak (DRY ihlali)
      2) Subquery ile sarmak (önce hesapla, sonra dışta filtrele/sırala)
    İkincisini seçtik — okuması da PostgreSQL'in optimize etmesi de daha kolay.

    İleride performans: PostGIS + ST_DWithin/GiST index çok daha hızlı
    olur. 9k satır için şu an gereksiz.
    """
    snap = _get_active_snapshot(db, tenant_id)

    R = 6_371_000  # Dünya yarıçapı, metre

    # Sorgu noktası — float değerleri SQL ifadesine sabit olarak gömüyoruz
    lat_rad = func.radians(literal(lat))
    lon_rad = func.radians(literal(lon))

    # Durak koordinatları (her satır için)
    stop_lat_rad = func.radians(Stop.stop_lat)
    stop_lon_rad = func.radians(Stop.stop_lon)

    dlat = stop_lat_rad - lat_rad
    dlon = stop_lon_rad - lon_rad

    a = (
        func.sin(dlat / 2) * func.sin(dlat / 2)
        + func.cos(lat_rad)
        * func.cos(stop_lat_rad)
        * func.sin(dlon / 2)
        * func.sin(dlon / 2)
    )
    distance_m_expr = 2 * R * func.asin(func.sqrt(a))

    # 1. İç sorgu: snapshot ve koordinat NULL filtresi + distance_m sütunu
    inner = (
        db.query(
            Stop.stop_id.label("stop_id"),
            Stop.stop_name.label("stop_name"),
            Stop.stop_lat.label("stop_lat"),
            Stop.stop_lon.label("stop_lon"),
            distance_m_expr.label("distance_m"),
        )
        .filter(Stop.snapshot_id == snap.id)
        .filter(Stop.stop_lat.isnot(None))
        .filter(Stop.stop_lon.isnot(None))
        .subquery()
    )

    # 2. Dış sorgu: yarıçap filtresi + sıralama + limit
    rows = (
        db.query(inner)
        .filter(inner.c.distance_m <= radius_m)
        .order_by(inner.c.distance_m.asc())
        .limit(limit)
        .all()
    )

    return {
        "tenant_id": tenant_id,
        "snapshot_id": snap.id,
        "query": {
            "lat": lat,
            "lon": lon,
            "radius_m": radius_m,
            "limit": limit,
        },
        "stop_count": len(rows),
        "stops": [
            {
                "stop_id": r.stop_id,
                "stop_name": r.stop_name,
                "stop_lat": r.stop_lat,
                "stop_lon": r.stop_lon,
                "distance_m": round(float(r.distance_m), 1),
            }
            for r in rows
        ],
    }
