from fastapi import FastAPI
from app.database import engine, Base
from app.models import gtfs  # noqa: F401
from app.routers import import_router, query_router

app = FastAPI(
    title="GTFS Mikroservis",
    description="Burulas ve diğer operatörler için GTFS veri servisi",
    version="0.1.0",
)

# Router'ları uygulamaya bağla
app.include_router(import_router.router)
app.include_router(query_router.router)

@app.on_event("startup")
def create_tables():
    Base.metadata.create_all(bind=engine)
    print("✅ Tablolar oluşturuldu")

@app.get("/health")
def health():
    return {"status": "ok"}