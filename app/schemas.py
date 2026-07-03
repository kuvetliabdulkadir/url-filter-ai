
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
# pydantic: gelen/giden verilerin formatini ve tipini kontrol eder
# ornek: birisi url yerine sayi gonderirse otomatik hata doner

#  giris modelleri (API'ye gelen veri) 

class URLAnalyzeRequest(BaseModel):
    """kullanici bu formatta url gonderir"""
    url: str = Field(..., description="analiz edilecek url", example="https://www.instagram.com")


# cikis modelleri (API'den donen veri) 

class URLAnalyzeResponse(BaseModel):
    """tek bir url analiz sonucu"""
    id: int
    url: str
    domain: Optional[str] = None

    category: str           # social / gambling / adult / safe / unknown
    decision: str           # ALLOW / WARN / BLOCK
    confidence: Optional[float] = None
    reasoning: Optional[str] = None

    method: str             # dns_check / keyword / llm / cache
    risk_score: Optional[float] = None
    keyword_hint: Optional[str] = None
    error_message: Optional[str] = None
    llm_model: Optional[str] = None

    cached: bool = False    # cache'den mi geldi yoksa yeni analiz mi
    hit_count: int = 1

    analyzed_at: Optional[datetime] = None

    # sqlalchemy modelinden otomatik cevirme icin
    model_config = {"from_attributes": True}


class URLHistoryItem(BaseModel):
    """bir url'in gecmis analiz kaydi"""
    id: int
    category: str
    decision: str
    confidence: Optional[float] = None
    reasoning: Optional[str] = None
    method: str
    content_hash: Optional[str] = None
    llm_model: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class URLHistoryResponse(BaseModel):
    """bir url'in tum gecmis analizleri"""
    url: str
    current_category: str
    current_decision: str
    total_analyses: int
    history: List[URLHistoryItem]

class URLListItem(BaseModel):
    """gecmis listesinde gosterilecek tek satir"""
    id: int
    url: str
    domain: Optional[str] = None
    category: str
    decision: str
    confidence: Optional[float] = None
    reasoning: Optional[str] = None
    method: str
    risk_score: Optional[float] = None
    keyword_hint: Optional[str] = None
    error_message: Optional[str] = None
    llm_model: Optional[str] = None
    hit_count: int = 1
    analyzed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class URLListResponse(BaseModel):
    """filtrelenebilir, sayfalanabilir tam liste"""
    total: int
    items: List[URLListItem]


class BulkDeleteRequest(BaseModel):
    """secilen id'leri toplu silmek icin"""
    ids: List[int] = Field(..., description="silinecek kayit id'leri")


class BulkDeleteResponse(BaseModel):
    deleted_count: int
    deleted_ids: List[int]
