import os
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from app.db import URLAnalysis, URLAnalysisHistory, compute_content_hash
from app.content_fetcher import extract_domain, check_dns, fetch_page_content
from app.prefilter import run_prefilter
from app.llm_client import classify_with_llm

load_dotenv()

# cache suresi - varsayilan 24 saat
# bu sure icinde ayni url+ayni hash gelirse llm'e sormaz
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "24"))




def analyze_url(url: str, db: Session) -> dict:

    """
    ana akis fonksiyonu - url alir, tum adimlari sirayla isletir, sonuc doner.
    
    akis:
    1. url temizle + domain cikar
    2. dns kontrol
    3. cache kontrol (db'de var mi + hash ayni mi + sure dolmamis mi)
    4. sayfa icerigini cek
    5. hash hesapla
    6. on-filtre (keyword)
    7. llm analizi (gerekirse)
    8. sonucu db'ye yaz
    9. cevabi don
    """

    # ---- 1. url temizle ve domain cikar ----
    
    # http/https yoksa ekle
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    # sondaki / ekle ki ayni sayfa farkli url gibi gorunmesin
    if not url.endswith("/"):
        url = url + "/"
    domain = extract_domain(url)

    # cache kontrol
    existing = db.query(URLAnalysis).filter(URLAnalysis.url == url).first()
    if existing:
        cache_deadline = datetime.utcnow() - timedelta(hours=CACHE_TTL_HOURS)
        if existing.analyzed_at and existing.analyzed_at > cache_deadline:
            existing.hit_count += 1
            db.commit()
            db.refresh(existing)
            return _to_response(existing, cached=True)

    # ---- 2. dns kontrol ----
    # domain dns'te yoksa devam etmeye gerek yok
    if not check_dns(domain):
        result = _save_result(db, url, domain, {
            "category": "unknown",
            "decision": "BLOCK",
            "confidence": 0.0,
            "reasoning": f"{domain} dns'te cozumlenemedi, domain mevcut degil",
            "method": "dns_check",
            "risk_score": 100.0,
            "keyword_hint": None,
            "error_message": "dns cozumleme basarisiz",
            "llm_model": None,
            "content_hash": None,
        })
        result["cached"] = False
        return result

    # ---- 3. sayfa icerigini cek ----
  
    # domain zaten bilinen bir site ise sayfayi cekmeye gerek yok
    domain_prefilter = run_prefilter(url, "", domain)
    if domain_prefilter["matched"] and domain_prefilter["confidence"] >= 0.9:
        result = _save_result(db, url, domain, {
            "category": domain_prefilter["category"],
            "decision": domain_prefilter["decision"],
            "confidence": domain_prefilter["confidence"],
            "reasoning": f"on-filtre ile tespit edildi: {domain_prefilter['keyword_hint']}",
            "method": "keyword",
            "risk_score": 90.0 if domain_prefilter["decision"] == "BLOCK" else 50.0,
            "keyword_hint": domain_prefilter["keyword_hint"],
            "error_message": None,
            "llm_model": None,
            "content_hash": None,
        })
        result["cached"] = False
        return result
    
    page = fetch_page_content(url)

    if not page["success"]:
        result = _save_result(db, url, domain, {
            "category": "unknown",
            "decision": "WARN",
            "confidence": 0.0,
            "reasoning": f"sayfa icerigi cekilemedi: {page['error']}",
            "method": "fetch_error",
            "risk_score": 50.0,
            "keyword_hint": None,
            "error_message": page["error"],
            "llm_model": None,
            "content_hash": None,
        })
        result["cached"] = False
        return result

    # ---- 4. hash hesapla ----
    content_hash = compute_content_hash(page["text"]) if page["text"] else None

    # ---- 5. cache kontrol ----
    # db'de bu url var mi? varsa hash ayni mi? sure dolmamis mi?
    existing = db.query(URLAnalysis).filter(URLAnalysis.url == url).first()

    if existing and content_hash:
        # hash ayni VE cache suresi dolmamis -> llm'e sormadan don
        cache_deadline = datetime.utcnow() - timedelta(hours=CACHE_TTL_HOURS)
        if existing.content_hash == content_hash and existing.analyzed_at > cache_deadline:
            existing.hit_count += 1
            db.commit()
            db.refresh(existing)
            return _to_response(existing, cached=True)

    # ---- 6. on-filtre (keyword/regex) ----
    prefilter = run_prefilter(url, page["text"], domain)

    if prefilter["matched"] and prefilter["confidence"] >= 0.9:
        # on-filtre yuksek guvenle eslesti, llm'e sormaya gerek yok
        result = _save_result(db, url, domain, {
            "category": prefilter["category"],
            "decision": prefilter["decision"],
            "confidence": prefilter["confidence"],
            "reasoning": f"on-filtre ile tespit edildi: {prefilter['keyword_hint']}",
            "method": "keyword",
            "risk_score": 90.0 if prefilter["decision"] == "BLOCK" else 50.0,
            "keyword_hint": prefilter["keyword_hint"],
            "error_message": None,
            "llm_model": None,
            "content_hash": content_hash,
        })
        result["cached"] = False
        return result

    # ---- 7. llm analizi ----
    # on-filtre emin degilse veya hic eslesmemisse llm'e sor
    llm_result = classify_with_llm(url, page["text"])

    # llm basarisiz olduysa ve on-filtre bir sey bulduysa, on-filtreye guven
    if not llm_result["success"] and prefilter["matched"]:
        result = _save_result(db, url, domain, {
            "category": prefilter["category"],
            "decision": prefilter["decision"],
            "confidence": prefilter["confidence"],
            "reasoning": f"llm basarisiz, on-filtre sonucu kullanildi: {prefilter['keyword_hint']}",
            "method": "keyword_fallback",
            "risk_score": 80.0 if prefilter["decision"] == "BLOCK" else 40.0,
            "keyword_hint": prefilter["keyword_hint"],
            "error_message": llm_result["error"],
            "llm_model": None,
            "content_hash": content_hash,
        })
        result["cached"] = False
        return result


    # on-filtre dusuk guvenle bir sey bulduysa ve llm farkli diyorsa
    # llm'in kararina guven (cunku llm icerigi okudu)
    risk_score = _calculate_risk_score(llm_result["category"], llm_result["confidence"])

    result = _save_result(db, url, domain, {
        "category": llm_result["category"],
        "decision": llm_result["decision"],
        "confidence": llm_result["confidence"],
        "reasoning": llm_result["reasoning"],
        "method": "llm",
        "risk_score": risk_score,
        "keyword_hint": prefilter["keyword_hint"] if prefilter["matched"] else None,
        "error_message": llm_result["error"],
        "llm_model": llm_result["model"],
        "content_hash": content_hash,
    })
    result["cached"] = False
    return result


def _calculate_risk_score(category: str, confidence: float) -> float:
    """kategoriye gore risk puani hesaplar (0-100)"""
    base_scores = {
        "adult": 95.0,
        "gambling": 90.0,
        "social": 40.0,
        "safe": 10.0,
        "unknown": 50.0,
    }
    base = base_scores.get(category, 50.0)
    # guven skoru dusukse risk puanini ortaya cek
    return round(base * confidence + 50.0 * (1 - confidence), 1)


def _save_result(db: Session, url: str, domain: str, data: dict) -> dict:
    """
    sonucu db'ye yazar. url varsa gunceller, yoksa yeni ekler.
    ayrica history tablosuna da log ekler.
    """
    existing = db.query(URLAnalysis).filter(URLAnalysis.url == url).first()

    if existing:
        # url zaten var -> guncelle
        existing.domain = domain
        existing.content_hash = data["content_hash"]
        existing.category = data["category"]
        existing.decision = data["decision"]
        existing.confidence = data["confidence"]
        existing.reasoning = data["reasoning"]
        existing.method = data["method"]
        existing.risk_score = data["risk_score"]
        existing.keyword_hint = data["keyword_hint"]
        existing.error_message = data["error_message"]
        existing.llm_model = data["llm_model"]
        existing.analyzed_at = datetime.now(timezone.utc)
        existing.hit_count += 1
        record = existing
    else:
        # yeni url -> ekle
        record = URLAnalysis(
            url=url,
            domain=domain,
            content_hash=data["content_hash"],
            category=data["category"],
            decision=data["decision"],
            confidence=data["confidence"],
            reasoning=data["reasoning"],
            method=data["method"],
            risk_score=data["risk_score"],
            keyword_hint=data["keyword_hint"],
            error_message=data["error_message"],
            llm_model=data["llm_model"],
        )
        db.add(record)

    db.flush()  # id atansin diye

    # history tablosuna log ekle (cache hit'lerde buraya gelmiyoruz zaten)
    history = URLAnalysisHistory(
        url_analysis_id=record.id,
        url=url,
        content_hash=data["content_hash"],
        category=data["category"],
        decision=data["decision"],
        confidence=data["confidence"],
        reasoning=data["reasoning"],
        method=data["method"],
        risk_score=data["risk_score"],
        llm_model=data["llm_model"],
    )
    db.add(history)
    db.commit()
    db.refresh(record)

    return _to_response(record, cached=False)


def _to_response(record: URLAnalysis, cached: bool) -> dict:
    """db kaydini api cevabi formatina cevirir"""
    return {
        "id": record.id,
        "url": record.url,
        "domain": record.domain,
        "category": record.category,
        "decision": record.decision,
        "confidence": record.confidence,
        "reasoning": record.reasoning,
        "method": record.method,
        "risk_score": record.risk_score,
        "keyword_hint": record.keyword_hint,
        "error_message": record.error_message,
        "llm_model": record.llm_model,
        "cached": cached,
        "hit_count": record.hit_count,
        "analyzed_at": record.analyzed_at,
    }