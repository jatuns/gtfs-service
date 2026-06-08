# Test Fixtures

## `mini_gtfs/`

Küçük, sentetik bir GTFS feed'i. Burulas verisinin **yapısını taklit eder**
ama sadece testlerin ihtiyaç duyduğu kadar veri içerir:

| Tablo | Satır |
|---|---|
| agency | 1 |
| routes | 6 (1, 15, 4A, B38, 101, 102) |
| stops | 11 (D0052 = ULUCAMI, D13-136-S = orphan, vb.) |
| calendar | 3 (WEEKDAY, WEEKEND, DAILY) |
| calendar_dates | 1 (23 Nisan istisna) |
| trips | 13 (Route 15: iki yön, 4A/B38: D0052 08-09 arası varış) |
| stop_times | 38 |

### Tasarım amacı

`tests/conftest.py`'deki "altın" değerlerle uyumlu:
- `KNOWN_STOP_ID = "D0052"` → ULUCAMI, koord (40.18351, 29.06127)
- `KNOWN_ROUTE_ID = "15"` → İki yönlü ring hat
- `KNOWN_DATE = "2026-04-15"` → Çarşamba, WEEKDAY service aktif
- `D13-136-S` → Yetim durak (stops'ta var, stop_times'da yok)
- 2026-04-15 08:00–09:00 arası D0052'de 6+ varış var

### CI'da otomatik yüklenir

`conftest.py`'de session-scoped autouse fixture `ensure_test_data()`:
- Lokalde aktif Burulas snapshot'ı varsa → hiçbir şey yapmaz
- CI'da boş DB ile başladığı için → mini_gtfs'i zip'leyip import eder

Bu sayede hem lokal hem CI'da tüm testler geçer.
