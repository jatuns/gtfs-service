from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import Base, engine
from app.models import gtfs  # noqa: F401  — modelleri Base.metadata'ya yükler
from app.routers import import_router, query_router


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

# Router'ları uygulamaya bağla
app.include_router(import_router.router)
app.include_router(query_router.router)


@app.get("/health")
def health():
    return {"status": "ok"}
