"""
Request Logging Middleware
--------------------------
Her isteği yapılandırılmış (JSON) formatta loglar:
  - method, path, query
  - status, süre (ms)
  - client IP
  - varsa kullanılan API key'in son 4 karakteri (full key asla loglanmaz!)

Neden JSON?
  Cloud-native loglama araçları (Datadog, CloudWatch, Loki, ELK)
  JSON satırlarını otomatik parse eder. Düz metin log'da grep
  yapmak için regex yazarsın, JSON'da {"status": 500} ile direkt
  filtrelersin.

Çıktı stdout'a — Docker/Uvicorn bunu logları toplar:
  {"event":"http_request","method":"GET","path":"/health","status":200,
   "duration_ms":3,"ip":"127.0.0.1"}
"""

import json
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("gtfs.http")
logger.setLevel(logging.INFO)

if not logger.handlers:
    # Stdout'a düz handler — Docker logs otomatik toplar
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Her isteği önce/sonra yakalar, JSON log üretir.

    Hassas veri loglama YOK:
      - Tam API key asla loglanmaz (sadece son 4 hane)
      - Request body loglanmaz (büyük zip'leri log'a yazmak istemiyoruz)
      - Cookie'ler atılır
    """

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            # Exception olursa yine de loglayalım
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.info(json.dumps({
                "event": "http_request",
                "method": request.method,
                "path": request.url.path,
                "status": 500,
                "duration_ms": duration_ms,
                "error": "unhandled_exception",
            }))
            raise

        duration_ms = int((time.perf_counter() - start) * 1000)

        # API key son 4 hane (telemetri için, full key gizli)
        api_key = request.headers.get("x-api-key")
        key_tail = api_key[-4:] if api_key and len(api_key) >= 4 else None

        log_entry = {
            "event": "http_request",
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query) if request.url.query else None,
            "status": status,
            "duration_ms": duration_ms,
            "ip": request.client.host if request.client else "unknown",
            "api_key_tail": key_tail,
        }
        # None değerleri at — JSON daha temiz
        log_entry = {k: v for k, v in log_entry.items() if v is not None}
        logger.info(json.dumps(log_entry))

        return response
