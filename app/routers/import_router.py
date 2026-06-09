"""
Import Router
-------------
POST /import endpoint'i burada.

Akış:
  1. Kullanıcı zip dosyasını, tenant_id ve label'ı gönderir
  2. Zip geçici diske kaydedilir
  3. gtfs_parser çağrılır
  4. Sonuç döndürülür
"""

import os
import tempfile
import shutil

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.api_key import verify_api_key
from app.services.gtfs_parser import import_gtfs

# APIRouter → endpoint'leri gruplamak için
# prefix="/import" → tüm endpoint'ler /import ile başlar
router = APIRouter(prefix="/import", tags=["Import"])


@router.post(
    "/",
    dependencies=[Depends(verify_api_key)],
    summary="GTFS zip dosyasını içe aktar (🔒 admin)",
    responses={
        401: {"description": "X-API-Key eksik veya yanlış"},
        400: {"description": "Yüklenen dosya .zip değil"},
        500: {"description": "Parser hatası (zip bozuk veya GTFS şeması eksik)"},
    },
)
async def import_gtfs_endpoint(
    file: UploadFile = File(...),        # zip dosyası
    tenant_id: str   = Form(...),        # "burulas", "eshot" vs.
    label: str       = Form(...),        # "burulas-2026-nisan"
    db: Session      = Depends(get_db)   # DB oturumu
):
    """
    GTFS zip dosyasını yükle ve DB'ye import et.

    - **file**: GTFS zip dosyası
    - **tenant_id**: Operatör kimliği (örn: burulas)
    - **label**: Import etiketi (örn: burulas-2026-nisan)
    """

    # 1. Sadece zip dosyası kabul et
    if not file.filename.endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Sadece .zip dosyası kabul edilir"
        )

    # 2. Zip'i geçici diske kaydet
    # tempfile.mktemp() → geçici bir dosya yolu üretir
    tmp_path = tempfile.mktemp(suffix=".zip")

    try:
        # Dosyayı diske yaz
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        print(f"📥 Dosya alındı: {file.filename} ({os.path.getsize(tmp_path)} byte)")

        # 3. Parser'ı çağır
        snapshot = import_gtfs(
            zip_path=tmp_path,
            tenant_id=tenant_id,
            label=label,
            db=db
        )

        # 4. Başarılı sonuç döndür
        return {
            "status":      "success",
            "snapshot_id": snapshot.id,
            "tenant_id":   snapshot.tenant_id,
            "label":       snapshot.label,
            "imported_at": snapshot.imported_at,
        }

    except Exception as e:
        # Hata olursa anlamlı mesaj döndür
        raise HTTPException(
            status_code=500,
            detail=f"Import hatası: {str(e)}"
        )

    finally:
        # Geçici dosyayı her durumda sil
        if os.path.exists(tmp_path):
            os.remove(tmp_path)