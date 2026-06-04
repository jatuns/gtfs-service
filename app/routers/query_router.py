"""
Query Router
------------
GTFS sorgu endpoint'leri.

Tüm endpoint'ler tenant_id ile filtrelenir ve o tenant'ın
aktif (is_active=True) snapshot'ını kullanır. Böylece eski
import'lar DB'de durur ama sorgular hep güncel veriden döner.

Endpoint'ler:
  GET /routes/{route_id}/stops      → hattın sıralı durakları
  GET /routes/{route_id}/trips      → hattın seferleri
  GET /stops/{stop_id}/arrivals     → durağa varış saatleri
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.gtfs import (
    GtfsSnapshot, Route, Stop, Trip, StopTime
)

router = APIRouter(tags=["Query"])


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
    limit: int = Query(200, ge=1, le=2000),
    tenant_id: str = Query("burulas"),
    db: Session = Depends(get_db),
):
    """
    Bir hatta ait seferleri listeler.

    Her trip için ilk durağın kalkış saatini (start_time) ekliyoruz,
    çünkü saat sırasına göre göstermek istiyoruz.
    """
    snap = _get_active_snapshot(db, tenant_id)

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

    rows = q.order_by(StopTime.departure_time.asc()).limit(limit).all()

    return {
        "tenant_id": tenant_id,
        "snapshot_id": snap.id,
        "route_id": route_id,
        "direction_id": direction_id,
        "service_id": service_id,
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
    route_id: str | None = Query(None, description="Belirli hat için filtre"),
    limit: int = Query(100, ge=1, le=1000),
    tenant_id: str = Query("burulas"),
    db: Session = Depends(get_db),
):
    """
    Bir durağa varış saatlerini döndürür.

    Her satır = bir sefer × bu durak.
    Saat aralığı verilirse o aralıkta filtrelenir.
    """
    snap = _get_active_snapshot(db, tenant_id)

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
