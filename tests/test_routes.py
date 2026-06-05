"""
Route endpoint'leri için smoke testler.
  - GET /routes/{route_id}/stops
  - GET /routes/{route_id}/trips
  - GET /routes/search
"""


# ─────────────────────────────────────────
# /routes/{route_id}/stops
# ─────────────────────────────────────────
class TestRouteStops:
    def test_returns_ordered_stops(self, client, known_route):
        r = client.get(f"/routes/{known_route['id']}/stops")
        assert r.status_code == 200
        data = r.json()

        assert data["route_id"] == known_route["id"]
        assert data["stop_count"] > 0
        assert len(data["stops"]) == data["stop_count"]

        # sequence artan sırada
        seqs = [s["sequence"] for s in data["stops"]]
        assert seqs == sorted(seqs)
        # ve 1'den başlamalı (GTFS konvansiyonu)
        assert seqs[0] == 1

    def test_each_stop_has_required_fields(self, client, known_route):
        r = client.get(f"/routes/{known_route['id']}/stops")
        data = r.json()
        for s in data["stops"]:
            assert s["stop_id"]
            assert s["stop_name"]
            assert s["arrival_time"]
            assert s["departure_time"]

    def test_direction_filter(self, client, known_route):
        """direction=0 ve direction=1 farklı sample_trip seçmeli."""
        r0 = client.get(
            f"/routes/{known_route['id']}/stops", params={"direction_id": 0}
        )
        r1 = client.get(
            f"/routes/{known_route['id']}/stops", params={"direction_id": 1}
        )
        # İkisi de 200 dönmeli (Ring hat olsa bile her iki yön mevcut)
        assert r0.status_code == 200
        assert r1.status_code == 200
        # Farklı trip_id seçilmeli (yönler aynı veri vermez)
        assert r0.json()["sample_trip_id"] != r1.json()["sample_trip_id"]

    def test_unknown_route_returns_404(self, client):
        r = client.get("/routes/AAAA_YOK_BU/stops")
        assert r.status_code == 404
        assert "bulunamadı" in r.json()["detail"]


# ─────────────────────────────────────────
# /routes/{route_id}/trips
# ─────────────────────────────────────────
class TestRouteTrips:
    def test_returns_trips_sorted_by_start(self, client, known_route):
        r = client.get(f"/routes/{known_route['id']}/trips", params={"limit": 50})
        assert r.status_code == 200
        data = r.json()

        assert data["trip_count"] > 0
        assert data["trip_count"] <= 50

        # start_time'a göre artan sırada
        starts = [t["start_time"] for t in data["trips"]]
        assert starts == sorted(starts)

        # Her trip'te beklenen alanlar
        for t in data["trips"]:
            assert t["trip_id"]
            assert t["service_id"]
            assert t["start_time"]

    def test_date_filter_returns_subset(self, client, known_route, known_date):
        """date filtresi olmadan ve olarak iki sorgu karşılaştırması."""
        all_r = client.get(
            f"/routes/{known_route['id']}/trips", params={"limit": 2000}
        )
        date_r = client.get(
            f"/routes/{known_route['id']}/trips",
            params={"limit": 2000, "date": known_date},
        )
        # date'li sonuç <= tüm sonuç (subset)
        assert date_r.json()["trip_count"] <= all_r.json()["trip_count"]

    def test_invalid_date_returns_400(self, client, known_route):
        r = client.get(
            f"/routes/{known_route['id']}/trips", params={"date": "not-a-date"}
        )
        assert r.status_code == 400
        assert "Geçersiz" in r.json()["detail"]


# ─────────────────────────────────────────
# /routes/search
# ─────────────────────────────────────────
class TestRouteSearch:
    def test_finds_known_route(self, client, known_route):
        r = client.get("/routes/search", params={"q": known_route["short_name"]})
        assert r.status_code == 200
        data = r.json()
        assert data["result_count"] > 0
        ids = [x["route_id"] for x in data["routes"]]
        assert known_route["id"] in ids

    def test_empty_q_returns_422(self, client):
        r = client.get("/routes/search", params={"q": ""})
        assert r.status_code == 422

    def test_no_match_returns_empty(self, client):
        r = client.get("/routes/search", params={"q": "ZZZ_HICBIR_HAT_YOK"})
        assert r.status_code == 200
        assert r.json()["result_count"] == 0
        assert r.json()["routes"] == []

    def test_limit_respected(self, client):
        r = client.get("/routes/search", params={"q": "1", "limit": 3})
        assert r.status_code == 200
        assert r.json()["result_count"] <= 3
