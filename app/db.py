import os
# ortam değişkenlerini okumak için
import hashlib
# hash
from datetime import datetime, timezone
# url ne zman kaydedıldı 
from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Float,
    ForeignKey, Index,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
# declarative_base: tablo siniflarinin miras alacagi temel sinif
# sessionmaker: veritabani islemleri icin oturum (session) olusturucu
# relationship: iki tablo arasindaki iliskiyi Python tarafinda tanimlar

from dotenv import load_dotenv
load_dotenv()
# .env dosyasindaki degiskenleri yukler

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/urlfilter",
)
# .env dosyasindan DB baglanti adresini al

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
# pool_pre_ping=True: her sorguda once "baglanti hala acik mı" diye kontrol eder
# baglanti kopmussa otomatik yeniden baglanir yoksa uygulama patlar

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# her istek icin ayri bir DB oturumu acilir, islem bitince kapanir
# autocommit=False: biz commit() demeden degisiklikler kaydedilmez (guvenlik)
# autoflush=False: biz istemedikce ara sorgular DB'ye gitmez (performans)

Base = declarative_base()
# tablo siniflarimiz bu Base'den turetilecek

def compute_content_hash(text: str) -> str:
    """sayfanin icerigindan parmak izi uretir, icerik ayni oldugu surece hash hep ayni kalir"""
    # fazla bosluklari temizle: "  merhaba   dunya  " -> "merhaba dunya"
    # boylece bosluk farki yuzunden gereksiz yeniden analiz yapilmaz
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class URLAnalysis(Base):
    """ana tablo - her url icin tek satir tutar, cache kontrolu buradan yapilir"""
    __tablename__ = "url_analyses"

    id = Column(Integer, primary_key=True, index=True)

    # unique=True: ayni url iki kere eklenemez, ikincide update yapilir
    url = Column(String, nullable=False, unique=True, index=True)
    # tldextract ile cikarilmis domain (ornek: bet365.com)
    domain = Column(String, nullable=True, index=True)

    # cache kontrolunun kalbi - sha256 hex = 64 karakter
    # ayni hash -> icerik degismemis -> llm'e sorma
    # farkli hash -> icerik degismis -> yeniden analiz et
    content_hash = Column(String(64), nullable=True, index=True)

    # analiz sonuclari
    category = Column(String, nullable=False)       # social / gambling / adult / safe / unknown
    decision = Column(String, nullable=False)        # ALLOW / WARN / BLOCK
    confidence = Column(Float, nullable=True)        # 0.0 - 1.0 arasi guven skoru
    reasoning = Column(String, nullable=True)        # neden bu karar verildi

    # analizin nasil yapildigi
    method = Column(String, nullable=False, default="keyword+llm")  # dns_check / keyword / llm / cache
    risk_score = Column(Float, nullable=True)        # 0-100 arasi risk puani
    keyword_hint = Column(String, nullable=True)     # on-filtrede yakalanan kelime varsa
    error_message = Column(String, nullable=True)    # hata olduysa ne oldugu
    llm_model = Column(String, nullable=True)        # hangi ollama modeli kullanildi

    # zaman bilgileri
    first_seen_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    analyzed_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),  # her update'te otomatik guncellenir
    )

    # bu url kac kere sorgulandi (cache hit dahil)
    hit_count = Column(Integer, default=1, nullable=False)

    # history tablosuyla iliski - bir url'in birden fazla analiz gecmisi olabilir
    history = relationship(
        "URLAnalysisHistory",
        back_populates="url_analysis",
        cascade="all, delete-orphan",
        order_by="desc(URLAnalysisHistory.created_at)",
    )

class URLAnalysisHistory(Base):
    """degismez log - her gercek analiz buraya eklenir, hicbir satir silinmez/guncellenmez"""
    __tablename__ = "url_analysis_history"

    id = Column(Integer, primary_key=True, index=True)

    # hangi url kaydina ait bu gecmis
    url_analysis_id = Column(
        Integer,
        ForeignKey("url_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )

    url = Column(String, nullable=False, index=True)
    content_hash = Column(String(64), nullable=True)

    # o anki analiz sonuclari
    category = Column(String, nullable=False)
    decision = Column(String, nullable=False)
    confidence = Column(Float, nullable=True)
    reasoning = Column(String, nullable=True)
    method = Column(String, nullable=False)
    risk_score = Column(Float, nullable=True)
    llm_model = Column(String, nullable=True)

    # bu kayit ne zaman olusturuldu
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True,
    )

    # ana tabloyla iliski (tersten erisim)
    url_analysis = relationship("URLAnalysis", back_populates="history")


# url + tarih uzerinde bilesik index
# "bu url'in gecmisini sirala" sorgusu hizli calsissin diye
Index(
    "ix_history_url_created",
    URLAnalysisHistory.url,
    URLAnalysisHistory.created_at,
)

def init_db():
    """tablolari olusturur, zaten varsa dokunmaz"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """her api istegi icin ayri bir db oturumu acar, istek bitince kapatir"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()