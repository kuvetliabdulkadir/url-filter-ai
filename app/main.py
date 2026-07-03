import os
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Request, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from app.db import init_db, get_db, URLAnalysis
from app.schemas import (
    URLAnalyzeRequest, URLAnalyzeResponse, URLHistoryResponse, URLHistoryItem,
    URLListResponse, URLListItem, BulkDeleteRequest, BulkDeleteResponse,
)
from app.analyzer import analyze_url

import logging

# guvenlik: hata loglarinda hassas bilgi gosterme
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


load_dotenv()

# .env'den api key'i al - bu olmadan uygulama baslamaz
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise RuntimeError("API_KEY ortam degiskeni tanimli degil! .env dosyasini kontrol et.")

# cors icin izin verilen adresler
# ornek: "https://url.kuvetliabdulkadir.com,http://localhost:3000"
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

# rate limiter - ayni ip'den dakikada max 20 istek
limiter = Limiter(key_func=get_remote_address)


# uygulama baslarken db tablolarini olustur
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="URL Filter AI",
    description="AI destekli URL filtreleme ve analiz sistemi",
    version="1.0.0",
    lifespan=lifespan,
)

# rate limit hatasi icin ozel cevap
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "cok fazla istek gonderdiniz, biraz bekleyin"}
    )

app.state.limiter = limiter

# cors ayarlari - sadece izin verilen adreslerden istek kabul et
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- api key dogrulama ----

def verify_api_key(
    request: Request,
    x_api_key: str = Header(default=None),
):
    # POST isteklerinde origin gelir, same-origin kontrolu calısır
    origin = request.headers.get("origin", "")
    referer = request.headers.get("referer", "")
    host = request.headers.get("host", "")
    is_same_origin = host and (host in origin or host in referer)
    if is_same_origin:
        return "frontend"

    # GET isteklerinde tarayici origin/referer gondermez
    # bu yuzden public read token ile de izin ver
    PUBLIC_READ_TOKEN = os.getenv("PUBLIC_READ_TOKEN", "")
    if PUBLIC_READ_TOKEN and x_api_key == PUBLIC_READ_TOKEN:
        return "public-read"

    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="gecersiz api anahtari")
    return x_api_key
# ---- endpoint'ler ----

@app.get("/health")
async def health_check():
    """sunucu calisiyor mu kontrolu - api key gerektirmez"""
    return {"status": "ok", "service": "url-filter-ai"}


@app.post("/analyze", response_model=URLAnalyzeResponse)
@limiter.limit("20/minute")
async def analyze(
    request: Request,
    body: URLAnalyzeRequest,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    try:
        result = analyze_url(body.url, db)
        return result
    except Exception as e:
        logger.error(f"analiz hatasi: {e}")
        raise HTTPException(status_code=500, detail="analiz sirasinda bir hata olustu")

@app.get("/history/{url:path}", response_model=URLHistoryResponse)
@limiter.limit("30/minute")
async def get_history(
    request: Request,
    url: str,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    """bir url'in tum analiz gecmisini doner"""
    record = db.query(URLAnalysis).filter(URLAnalysis.url == url).first()
    if not record:
        raise HTTPException(status_code=404, detail="bu url daha once analiz edilmemis")

    return URLHistoryResponse(
        url=record.url,
        current_category=record.category,
        current_decision=record.decision,
        total_analyses=len(record.history),
        history=[URLHistoryItem.model_validate(h) for h in record.history],
    )


@app.get("/list", response_model=URLListResponse)
@limiter.limit("30/minute")
async def list_history(
    request: Request,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key),
    category: Optional[str] = Query(default=None),
    decision: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """tum taramalarin filtrelenebilir, sayfalanabilir listesi"""
    q = db.query(URLAnalysis)
    if category:
        q = q.filter(URLAnalysis.category == category)
    if decision:
        q = q.filter(URLAnalysis.decision == decision)

    total = q.count()
    items = (
        q.order_by(URLAnalysis.analyzed_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return URLListResponse(
        total=total,
        items=[URLListItem.model_validate(i) for i in items],
    )


@app.delete("/list/{record_id}")
@limiter.limit("30/minute")
async def delete_record(
    request: Request,
    record_id: int,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    """tek bir kaydi siler"""
    record = db.query(URLAnalysis).filter(URLAnalysis.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="kayit bulunamadi")
    db.delete(record)
    db.commit()
    return {"deleted": True, "id": record_id}


@app.post("/list/bulk-delete", response_model=BulkDeleteResponse)
@limiter.limit("10/minute")
async def bulk_delete(
    request: Request,
    body: BulkDeleteRequest,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    """secilen id'leri toplu siler"""
    if not body.ids:
        return BulkDeleteResponse(deleted_count=0, deleted_ids=[])

    records = db.query(URLAnalysis).filter(URLAnalysis.id.in_(body.ids)).all()
    deleted_ids = [r.id for r in records]
    for r in records:
        db.delete(r)
    db.commit()
    return BulkDeleteResponse(deleted_count=len(deleted_ids), deleted_ids=deleted_ids)


@app.get("/stats")
@limiter.limit("30/minute")
async def get_stats(
    request: Request,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    """genel istatistikler - kac url analiz edilmis, kategori dagilimi vs."""
    total = db.query(URLAnalysis).count()
    categories = {}
    for cat in ["social", "gambling", "adult", "safe", "unknown"]:
        categories[cat] = db.query(URLAnalysis).filter(URLAnalysis.category == cat).count()

    decisions = {}
    for dec in ["ALLOW", "WARN", "BLOCK"]:
        decisions[dec] = db.query(URLAnalysis).filter(URLAnalysis.decision == dec).count()

    return {
        "total_urls": total,
        "categories": categories,
        "decisions": decisions,
    }


# static dosyalari en sona mount et (route cakismasi olmasin)
# arayuz dosyalari burada olacak
app.mount("/", StaticFiles(directory="static", html=True), name="static")
