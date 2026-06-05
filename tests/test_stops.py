"""
Stop endpoint'leri için smoke testler.
  - GET /stops/{stop_id}/arrivals
  - GET /stops/{stop_id}/next
  - GET /stops/nearby
  - GET /stops/search
"""


# ─────────────────────────────────────────
# /stops/{stop_id}/arrivals
# ─────────────────────────────────────────
class TestStopArrivals:
    def test_returns_arrivals_for_central_stop(self, client, known_stop, known_date):
        r = client.get(
            f"/stops/{known_stop['id']}/arrivals",
            params={"date": known_date, "from_time": "08:00:00", "to_time": "09:00:00"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["stop_name"] == known_stop["name"]
        assert data["arrival_count"] > 0

    def test_arrivals_sorted_by_time(self, client, known_stop, known_date):
        r = client.get(
            f"/stops/{known_stop['id']}/arrivals",
            params={"date": known_date, "limit": 50},
        )
        times = [a["arrival_time"] for a in r.json()["arrivals"]]
        assert times == sorted(times)

    def test_time_window_respected(self, client, known_stop, known_date):
        r = client.get(
            f"/stops/{known_stop['id']}/arrivals",
            params={
                "date": known_date,
                "from_time": "08:00:00",
                "to_time": "09:00:00",
                "limit": 200,
            },
        )
        for a in r.json()["arrivals"]:
            assert "08:00:00" <= a["arrival_time"] <= "09:00:00"

    def test_route_filter(self, client, known_stop, known_date):
        """Eğer bir route filtresi verirsek tüm sonuçlar o route'a ait olmalı."""
        # Önce filtresiz sorgu ile bu durağa gelen bir route_id bul
        all_r = client.get(
            f"/stops/{known_stop['id']}/arrivals",
            params={"date": known_date, "limit": 5},
        )
        arrivals = all_r.json()["arrivals"]
        assert len(arrivals) > 0
        sample_route = arrivals[0]["route_id"]

        # Sonra o route ile filtre uygula
        filtered = client.get(
            f"/stops/{known_stop['id']}/arrivals",
            params={"date": known_date, "route_id": sample_route, "limit": 50},
        )
        for a in filtered.json()["arrivals"]:
            assert a["route_id"] == sample_route

    def test_unknown_stop_returns_404(self, client):
        r = client.get("/stops/YOK_BU_DURAK/arrivals")
        assert r.status_code == 404

    def test_orphan_stop_returns_empty(self, client):
        """D13-136-S = bilinen yetim durak (1864 yetimden biri)."""
        r = client.get("/stops/D13-136-S/arrivals")
        assert r.status_code == 200
        assert r.json()["arrival_count"] == 0


# ─────────────────────────────────────────
# /stops/{stop_id}/next
# ─────────────────────────────────────────
class TestStopNext:
    def test_returns_structure(self, client, known_stop):
        r = client.get(f"/stops/{known_stop['id']}/next")
        assert r.status_code == 200
        data = r.json()
        assert data["stop_id"] == known_stop["id"]
        assert "now_local" in data
        assert "weekday" in data or data.get("note")
        assert isinstance(data["arrival_count"], int)
        assert isinstance(data["arrivals"], list)

    def test_count_respected(self, client, known_stop):
        r = client.get(f"/stops/{known_stop['id']}/next", params={"count": 5})
        assert r.status_code == 200
        assert len(r.json()["arrivals"]) <= 5


# ─────────────────────────────────────────
# /stops/nearby
# ─────────────────────────────────────────
class TestStopsNearby:
    def test_finds_known_stop_near_self(self, client, known_stop):
        r = client.get(
            "/stops/nearby",
            params={
                "lat": known_stop["lat"],
                "lon": known_stop["lon"],
                "radius_m": 100,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["stop_count"] > 0
        # Kendi koordinatına en yakın durak: kendisi (veya çok yakını)
        first = data["stops"][0]
        assert first["distance_m"] < 10  # en fazla 10 metre

    def test_distance_sorted_ascending(self, client, known_stop):
        r = client.get(
            "/stops/nearby",
            params={
                "lat": known_stop["lat"],
                "lon": known_stop["lon"],
                "radius_m": 1000,
                "limit": 20,
            },
        )
        distances = [s["distance_m"] for s in r.json()["stops"]]
        assert distances == sorted(distances)

    def test_radius_respected(self, client, known_stop):
        r = client.get(
            "/stops/nearby",
            params={
                "lat": known_stop["lat"],
                "lon": known_stop["lon"],
                "radius_m": 500,
            },
        )
        for s in r.json()["stops"]:
            assert s["distance_m"] <= 500

    def test_wider_radius_returns_at_least_as_many(self, client, known_stop):
        narrow = client.get(
            "/stops/nearby",
            params={"lat": known_stop["lat"], "lon": known_stop["lon"], "radius_m": 200, "limit": 200},
        )
        wide = client.get(
            "/stops/nearby",
            params={"lat": known_stop["lat"], "lon": known_stop["lon"], "radius_m": 2000, "limit": 200},
        )
        assert wide.json()["stop_count"] >= narrow.json()["stop_count"]

    def test_invalid_lat_returns_422(self, client):
        r = client.get(
            "/stops/nearby", params={"lat": 200, "lon": 29, "radius_m": 100}
        )
        assert r.status_code == 422

    def test_remote_point_returns_empty(self, client):
        """Bursa'dan binlerce km uzakta (Pasifik Okyanusu) → 0 durak."""
        r = client.get(
            "/stops/nearby",
            params={"lat": 0, "lon": -150, "radius_m": 10_000},
        )
        assert r.status_code == 200
        assert r.json()["stop_count"] == 0


# ─────────────────────────────────────────
# /stops/search
# ─────────────────────────────────────────
class TestStopSearch:
    def test_finds_known_stop_by_name(self, client, known_stop):
        r = client.get("/stops/search", params={"q": known_stop["name"]})
        assert r.status_code == 200
        names = [s["stop_name"] for s in r.json()["stops"]]
        assert known_stop["name"] in names

    def test_finds_by_stop_id(self, client, known_stop):
        r = client.get("/stops/search", params={"q": known_stop["id"]})
        assert r.status_code == 200
        ids = [s["stop_id"] for s in r.json()["stops"]]
        assert known_stop["id"] in ids

    def test_empty_q_returns_422(self, client):
        r = client.get("/stops/search", params={"q": ""})
        assert r.status_code == 422

    def test_results_deterministic(self, client):
        """
        Sıralama PostgreSQL ORDER BY stop_name'e bırakılır.
        Locale'a duyarlı sıralama (UTF-8 collation) Python sorted() ile
        bire bir eşleşmiyor — boşluk, rakam, parantez gibi noktalama
        karakterleri farklı kurallarla sıralanıyor.

        Bu test sadece deterministik olduğunu doğruluyor:
        aynı sorgu iki kere koşulunca aynı sırada geliyor.
        Asıl 'doğru sıralama' kontrolü endpoint koduna ve PostgreSQL'e
        güveniyoruz (ORDER BY stop_name kullanıyor).
        """
        r1 = client.get("/stops/search", params={"q": "ulu", "limit": 50})
        r2 = client.get("/stops/search", params={"q": "ulu", "limit": 50})
        names1 = [s["stop_name"] for s in r1.json()["stops"]]
        names2 = [s["stop_name"] for s in r2.json()["stops"]]
        assert names1 == names2
        assert len(names1) > 0
