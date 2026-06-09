"""
Rate Limiting Middleware
------------------------
IP başına dakikada en fazla N istek. Aşan → 429 Too Many Requests.

Tasarım:
  - "Sliding window" — son 60 saniye içindeki isteklerin sayısı bakılır
  - Bellekte tutulur (process-local)
    * Avantaj: ek bağımlılık yok, hızlı
    * Dezavantaj: tek instance — birden çok uvicorn worker'ı varsa
      her birinin sayacı ayrı. Production'da Redis kullanılır.
  - X-Forwarded-For header'ı varsa onu okur (reverse proxy arkasında IP)
  - /health hariç tutulur (load balancer hep çağırır, throttle etmek anlamsız)

Yapılandırma (.env):
  RATE_LIMIT_PER_MINUTE=60   # default 60, 0 = devre dışı

Kullanım (main.py):
  from app.security.rate_limit import RateLimitMiddleware
  app.add_middleware(RateLimitMiddleware)
"""

import os
import time
from collections import defaultdict, deque
from typing import Deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


# Bypass edilen path'ler — bunlar her zaman geçer
_EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Starlette/FastAPI middleware'i. Her istek için:
      1. Limit ayarını oku (her seferinde — testler set/unset edebilsin)
      2. Path muafsa → bırak geç
      3. IP'yi tespit et
      4. Bu IP'nin son 60 saniyedeki istek sayısını hesapla
      5. Limit aşıldıysa → 429 + Retry-After header
      6. Değilse → isteği bir sonraki katmana ilet
    """

    def __init__(self, app):
        super().__init__(app)
        # IP → deque[timestamp] sözlüğü
        # deque (double-ended queue): hızlı popleft için
        self._buckets: dict[str, Deque[float]] = defaultdict(deque)

    def _limit(self) -> int:
        """Env'den dakikalık limit. 0 ya da geçersiz → 0 (devre dışı)."""
        try:
            return max(0, int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")))
        except ValueError:
            return 60

    def _client_ip(self, request: Request) -> str:
        """
        Reverse proxy (Nginx, ALB) arkasındaysa X-Forwarded-For doğru IP'yi
        verir. Yoksa request.client.host'a düş.
        """
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # XFF "client, proxy1, proxy2" formatında — ilk eleman client
            return xff.split(",")[0].strip()
        if request.client is None:
            return "unknown"
        return request.client.host

    async def dispatch(self, request: Request, call_next):
        limit = self._limit()
        if limit == 0:
            return await call_next(request)

        # Muaf path'ler
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        # OPTIONS preflight'lar limitten muaf
        if request.method == "OPTIONS":
            return await call_next(request)

        ip = self._client_ip(request)
        now = time.time()
        cutoff = now - 60.0  # son 60 saniye

        bucket = self._buckets[ip]

        # Eski timestamp'leri at — sliding window'un kayan kısmı
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            # Limit aşıldı
            retry_after = max(1, int(bucket[0] + 60 - now))
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Rate limit aşıldı: dakikada en fazla {limit} istek."
                    ),
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        # Bu isteği kaydet, devam et
        bucket.append(now)
        return await call_next(request)
