import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.models import gtfs  # noqa: F401  — modelleri Base.metadata'ya yükler
from app.routers import import_router, query_router
from app.security.logging import RequestLoggingMiddleware
from app.security.rate_limit import RateLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan hook'u.
    Eskiden @app.on_event("startup") kullanıyorduk; FastAPI 0.93+ ile
    deprecated. Lifespan tek yerden hem başlangıç hem kapanış mantığını
    tutuyor.

    Şu an sadece tabloları kuruyoruz (zaten varsa dokunmaz, idempotent).
    İleride: warm-up cache, connection pre-ping, vs. eklenebilir.
    """
    # Startup
    Base.metadata.create_all(bind=engine)
    print("✅ Tablolar oluşturuldu")
    yield
    # Shutdown (şimdilik bir şey yok)


app = FastAPI(
    title="GTFS Mikroservis",
    description="Burulas ve diğer operatörler için GTFS veri servisi",
    version="0.1.0",
    lifespan=lifespan,
)

# ─── Middleware'ler ──────────────────────────────────────────
# Sıra ÖNEMLİ: en son add_middleware en ÖNCE çalışır (LIFO).
# Yani isteğin yolu:
#   gelen istek → Logging → RateLimit → CORS → router → endpoint
#                                                        ↑ (dönüş ters)
# Logging en dışta çünkü hata olsa bile log almalı.

# 1) Logging — her isteği JSON formatında stdout'a yazar
app.add_middleware(RequestLoggingMiddleware)

# 2) Rate limit — IP başına dakikada N istek
app.add_middleware(RateLimitMiddleware)

# 3) CORS — hangi tarayıcı origin'inden çağrı kabul edileceği
#    Frontend localhost:3000 (CRA) veya 5173 (Vite) gibi farklı portta
#    çalışırken bu olmadan tarayıcı isteği bloklar.
_cors_origins_raw = os.getenv("CORS_ORIGINS", "*")
_cors_origins = (
    [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
    if _cors_origins_raw != "*"
    else ["*"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Router'ları uygulamaya bağla
app.include_router(import_router.router)
app.include_router(query_router.router)

# ─── Static dosyalar (Leaflet demo) ──────────────────────────
# /demo  → demo.html (kullanıcının tarayıcısı için kısa yol)
# /static → tüm static dosyalar (ileride css/img eklenebilir)
_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/demo", include_in_schema=False)
def demo():
    """Leaflet tabanlı interaktif harita demosu."""
    return FileResponse(_STATIC_DIR / "demo.html")


@app.get("/health")
def health():
    return {"status": "ok"}
