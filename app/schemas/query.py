"""
Query Router için Pydantic Response Modelleri
---------------------------------------------
Her endpoint'in dönüş şeması burada tanımlı.

Faydası:
  1. FastAPI cevabı bu şemaya göre serileştirir → tip uyumsuzluğu
     erken yakalanır (örn yanlışlıkla None döndürdüğümüz alan).
  2. Swagger UI'da her endpoint için tam JSON şeması, örnek cevap,
     alan açıklaması görünür → API'yi kullanan kişi belge okumadan
     anlıyor.
  3. OpenAPI şemasından otomatik TypeScript/Dart vs. istemci kodu
     üretilebilir.

Tasarım kararları:
  - Ortak nested tipler (StopBrief, ArrivalEntry, ...) tekrar
    yazılmasın diye en üstte.
  - Esnek tipler (Optional[int], Optional[str]) çünkü Burulas
    verisi her zaman dolu değil (örn wheelchair_boarding null olur).
  - Field(..., description="...") ile her alana açıklama → Swagger
    bunu doğrudan UI'da gösterir.
"""

from typing import Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────
# ORTAK NESTED TİPLER
# ─────────────────────────────────────────

class StopBrief(BaseModel):
    """Bir durağın özet bilgisi — listelerde tekrar tekrar kullanılır."""
    stop_id: str
    stop_name: Optional[str] = None
    stop_lat: Optional[float] = None
    stop_lon: Optional[float] = None


class StopWithDistance(StopBrief):
    """StopBrief + mesafe (nearby endpoint için)."""
    distance_m: float = Field(..., description="Sorgu noktasına metre cinsinden mesafe")


class StopWithDisabledInfo(StopBrief):
    """StopBrief + wheelchair_boarding (search endpoint için)."""
    wheelchair_boarding: Optional[int] = Field(
        None, description="0=bilgi yok, 1=erişilebilir, 2=erişilemez"
    )


class RouteBrief(BaseModel):
    """Bir hattın özet bilgisi."""
    route_id: str
    route_short_name: Optional[str] = None
    route_long_name: Optional[str] = None
    agency_id: Optional[str] = None
    route_type: Optional[int] = Field(None, description="GTFS route_type (3=otobüs)")


class TripBrief(BaseModel):
    """Bir seferin liste görünümü (route trips için)."""
    trip_id: str
    service_id: Optional[str] = None
    direction_id: Optional[int] = Field(None, description="0=gidiş, 1=dönüş")
    shape_id: Optional[str] = None
    trip_headsign: Optional[str] = None
    start_time: Optional[str] = Field(None, description="İlk durağın departure_time'ı (HH:MM:SS)")


class RouteStopEntry(BaseModel):
    """Bir hattın stop dizisindeki bir durak (sequence + saat)."""
    sequence: int
    stop_id: str
    stop_name: Optional[str] = None
    stop_lat: Optional[float] = None
    stop_lon: Optional[float] = None
    arrival_time: Optional[str] = None
    departure_time: Optional[str] = None


class TripStopEntry(RouteStopEntry):
    """Trip detayındaki durak — RouteStopEntry + pickup/drop_off + mesafe."""
    pickup_type: Optional[int] = None
    drop_off_type: Optional[int] = None
    shape_dist_traveled: Optional[float] = None


class ArrivalEntry(BaseModel):
    """Bir durağa varış bilgisi — /arrivals ve /next için ortak."""
    arrival_time: str
    departure_time: Optional[str] = None
    trip_id: str
    route_id: str
    direction_id: Optional[int] = None
    trip_headsign: Optional[str] = None
    service_id: Optional[str] = None
    stop_sequence: Optional[int] = Field(
        None, description="Bu durak o sefer için kaçıncı durak"
    )


# ─────────────────────────────────────────
# ENVELOPE — TÜM CEVAPLARDA ORTAK ALANLAR
# ─────────────────────────────────────────

class TenantEnvelope(BaseModel):
    """tenant_id + snapshot_id — her cevapta var."""
    tenant_id: str
    snapshot_id: int


# ─────────────────────────────────────────
# /routes/{route_id}/stops
# ─────────────────────────────────────────

class RouteStopsResponse(TenantEnvelope):
    route_id: str
    direction_id: Optional[int] = None
    sample_trip_id: str = Field(..., description="Stop dizisi bu trip'ten örneklendi")
    stop_count: int
    stops: list[RouteStopEntry]


# ─────────────────────────────────────────
# /routes/{route_id}/trips
# ─────────────────────────────────────────

class RouteTripsResponse(TenantEnvelope):
    route_id: str
    direction_id: Optional[int] = None
    service_id: Optional[str] = None
    date: Optional[str] = Field(None, description="Filtre tarihi (YYYY-MM-DD), verilmemişse null")
    trip_count: int
    trips: list[TripBrief]


# ─────────────────────────────────────────
# /stops/{stop_id}/arrivals
# ─────────────────────────────────────────

class ArrivalFilters(BaseModel):
    from_time: Optional[str] = None
    to_time: Optional[str] = None
    date: Optional[str] = None
    route_id: Optional[str] = None
    limit: int


class StopArrivalsResponse(TenantEnvelope):
    stop_id: str
    stop_name: Optional[str] = None
    stop_lat: Optional[float] = None
    stop_lon: Optional[float] = None
    filters: ArrivalFilters
    arrival_count: int
    arrivals: list[ArrivalEntry]


# ─────────────────────────────────────────
# /stops/{stop_id}/next
# ─────────────────────────────────────────

class StopNextResponse(TenantEnvelope):
    stop_id: str
    stop_name: Optional[str] = None
    stop_lat: Optional[float] = None
    stop_lon: Optional[float] = None
    now_local: str = Field(..., description="ISO 8601 yerel zaman (Europe/Istanbul)")
    date: str
    weekday: Optional[str] = Field(None, description="monday..sunday")
    active_service_count: Optional[int] = Field(
        None,
        description="Bugün için aktif servis sayısı; 0 ise note alanı dolar",
    )
    arrival_count: int
    arrivals: list[ArrivalEntry]
    note: Optional[str] = Field(
        None, description="Aktif servis yoksa açıklama mesajı"
    )


# ─────────────────────────────────────────
# /stops/nearby
# ─────────────────────────────────────────

class NearbyQuery(BaseModel):
    lat: float
    lon: float
    radius_m: int
    limit: int


class StopsNearbyResponse(TenantEnvelope):
    query: NearbyQuery
    stop_count: int
    stops: list[StopWithDistance]


# ─────────────────────────────────────────
# /routes/search
# ─────────────────────────────────────────

class SearchQuery(BaseModel):
    q: str
    limit: int


class RouteSearchResponse(TenantEnvelope):
    query: SearchQuery
    result_count: int
    routes: list[RouteBrief]


# ─────────────────────────────────────────
# /stops/search
# ─────────────────────────────────────────

class StopSearchResponse(TenantEnvelope):
    query: SearchQuery
    result_count: int
    stops: list[StopWithDisabledInfo]


# ─────────────────────────────────────────
# /trips/{trip_id}
# ─────────────────────────────────────────

class TripDetailResponse(TenantEnvelope):
    trip_id: str
    route_id: str
    route_short_name: Optional[str] = None
    route_long_name: Optional[str] = None
    service_id: Optional[str] = None
    direction_id: Optional[int] = None
    shape_id: Optional[str] = None
    trip_headsign: Optional[str] = None
    wheelchair_accessible: Optional[int] = None
    bikes_allowed: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    stop_count: int
    stops: list[TripStopEntry]


# ─────────────────────────────────────────
# /journey — Yolculuk planlama
# ─────────────────────────────────────────

class JourneyLeg(BaseModel):
    """Tek seferli (aktarmasız) bir yolculuk etabı."""
    trip_id: str
    route_id: str
    route_short_name: Optional[str] = None
    trip_headsign: Optional[str] = None

    from_stop_id: str
    from_stop_name: Optional[str] = None
    from_stop_sequence: int
    departure_time: str = Field(..., description="HH:MM:SS")

    to_stop_id: str
    to_stop_name: Optional[str] = None
    to_stop_sequence: int
    arrival_time: str = Field(..., description="HH:MM:SS")

    intermediate_stop_count: int = Field(
        ..., description="Biniş ile iniş arası kaç durak geçilecek"
    )
    duration_seconds: int = Field(
        ..., description="Yolculuk süresi (saniye)"
    )


class JourneyQuery(BaseModel):
    from_stop: str
    to_stop: str
    from_time: str
    date: str
    limit: int


class JourneyResponse(TenantEnvelope):
    query: JourneyQuery
    weekday: str = Field(..., description="monday..sunday")
    active_service_count: int
    journey_count: int
    direct_journeys: list[JourneyLeg] = Field(
        default_factory=list,
        description="Aktarmasız yolculuklar — arrival_time'a göre artan sırada",
    )
    note: Optional[str] = None
