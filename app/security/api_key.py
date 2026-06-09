"""
API Key Authentication
----------------------
Bazı endpoint'ler 'admin' işlemlerdir (örn POST /import/ — DB'ye veri yazar).
Bunları açık bırakırsak isteyen anonim kullanıcı zip yükleyip DB'mizi
kirletebilir. Çözüm: X-API-Key header'ı zorunlu kılmak.

Kullanım (endpoint'te):
    from app.security.api_key import verify_api_key
    from fastapi import Depends

    @router.post("/admin/...", dependencies=[Depends(verify_api_key)])
    def admin_endpoint(...):
        ...

Veya parametre olarak:
    @router.post("/admin/...")
    def admin_endpoint(_: str = Depends(verify_api_key)):
        ...

Çağrı:
    curl -X POST http://localhost:8000/import/ \\
         -H "X-API-Key: <secret>" -F file=@gtfs.zip ...

Eksik veya yanlış key → 401 Unauthorized.

Tasarım kararları:
  - API key'ler .env'den okunur (gizli, git'e gitmez)
  - Birden fazla key destekli (virgülle ayrılır) → çok kullanıcılı senaryoya hazır
  - Şu an seviye yok (tek tier 'admin'); ileride 'read-only key' eklenebilir
  - Production'a uyarlama: DB'de saklı API key tablosu + rotasyon
"""

import os

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

# Postman vs. curl'da görsel olarak en yaygın kullanılan header adı
_HEADER_NAME = "X-API-Key"

# auto_error=False → header eksikse Security() None döndürür, biz 401 atarız
# (auto_error=True olsa 403 atardı, bizim için 401 daha doğru semantik)
_api_key_header = APIKeyHeader(name=_HEADER_NAME, auto_error=False)


def _load_valid_keys() -> set[str]:
    """
    .env'den 'ADMIN_API_KEYS' değişkenini virgülle ayırarak set'e çevir.
    Boş veya tanımsızsa boş set döner (=> hiçbir key kabul edilmez).

    Her istekte yeniden okur — testlerin set/unset edebilmesi için.
    Performans endişesi yok: os.getenv mikrosaniyelik iş.
    """
    raw = os.getenv("ADMIN_API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def verify_api_key(api_key: str | None = Security(_api_key_header)) -> str:
    """
    Geçerli bir API key gönderildiyse döndürür; aksi halde 401 atar.

    Bu fonksiyon FastAPI dependency'sidir — endpoint'lerde Depends(...)
    ile kullanılır. FastAPI Security/APIKeyHeader sayesinde Swagger UI'da
    'Authorize' butonunda görünür → kullanıcı bir kere key girer, tüm
    isteklere otomatik eklenir.
    """
    valid = _load_valid_keys()
    if not valid:
        # Sunucu tarafında hiç key tanımlı değilse → konfigürasyon hatası
        raise HTTPException(
            status_code=503,
            detail="API key doğrulama yapılandırılmamış (ADMIN_API_KEYS boş).",
        )
    if api_key is None or api_key not in valid:
        raise HTTPException(
            status_code=401,
            detail=f"Geçersiz veya eksik {_HEADER_NAME}.",
        )
    return api_key
