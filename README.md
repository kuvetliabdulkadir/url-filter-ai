# URL Filter AI

Yapay zeka destekli URL analiz ve içerik filtreleme sistemi. Verilen URL'nin içeriğini çekip, çok katmanlı bir analiz hattından geçirerek kategori (safe/social/gambling/adult) ve karar (ALLOW/WARN/BLOCK) üretir.

**Canlı demo:** https://url.kuvetliabdulkadir.com

---

## İçindekiler

- [Özellikler](#özellikler)
- [Mimari](#mimari)
- [Analiz Akışı](#analiz-akışı)
- [Teknoloji Stack'i](#teknoloji-stacki)
- [Kurulum](#kurulum)
  - [Ön Gereksinimler](#ön-gereksinimler)
  - [Ollama Kurulumu](#ollama-kurulumu)
  - [Projeyi Çalıştırma](#projeyi-çalıştırma)
- [Ortam Değişkenleri](#ortam-değişkenleri)
- [API Endpoint'leri](#api-endpointleri)
- [Frontend](#frontend)
- [Risk Skoru Hesaplama](#risk-skoru-hesaplama)
- [Cache Mekanizması](#cache-mekanizması)
- [Rate Limiting ve Güvenlik](#rate-limiting-ve-güvenlik)
- [Deploy (VPS + Nginx + Cloudflare)](#deploy-vps--nginx--cloudflare)
- [Proje Yapısı](#proje-yapısı)

---

## Özellikler

-  **Yerel LLM ile analiz** — Ollama üzerinden `qwen2.5:7b` modeli, dışa veri gitmez
-  **Çok katmanlı hızlı ön filtre** — bilinen bahis/yetişkin domainleri LLM'e gitmeden anında yakalanır
-  **Akıllı cache** — içerik hash'i ile aynı URL tekrar analiz edilmez, süre dolunca yenilenir
-  **Detaylı geçmiş paneli** — filtrelenebilir, çoklu seçim, tekil/toplu silme
-  **API key + public read token** — dış istekler için yazma koruması, frontend için okuma izni
-  **Rate limiting** — IP başına dakika bazlı istek sınırı (slowapi)
-  **Türkçe LLM promptu** — açıklamalar tutarlı şekilde Türkçe döner
-  **Docker Compose ile tek komut deploy**

---

## Mimari

```
┌──────────────┐        ┌────────────────┐        ┌──────────────┐
│   Kullanıcı  │──HTTPS→│  Cloudflare    │──HTTPS→│    Nginx     │
└──────────────┘        └────────────────┘        └──────┬───────┘
                                                          │ reverse proxy
                                                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                       Docker Compose Ağı                          │
│                                                                   │
│   ┌────────────────┐      ┌──────────────┐                       │
│   │   FastAPI      │─────→│  PostgreSQL  │                       │
│   │   (app)        │      │  (db)        │                       │
│   └───────┬────────┘      └──────────────┘                       │
│           │                                                       │
│           │ host.docker.internal:11434                            │
└───────────┼───────────────────────────────────────────────────────┘
            ▼
    ┌───────────────┐
    │  Ollama Host  │  (qwen2.5:7b)
    └───────────────┘
```

---

## Analiz Akışı

Bir URL `/analyze` endpoint'ine geldiğinde şu adımlardan geçer:

1. **URL doğrulama** — geçerli mi, şema var mı, normalize edilir (trailing slash)
2. **DNS kontrolü** — domain gerçekten çözümleniyor mu
3. **Domain ön filtre** — bilinen kötü domain listesinde mi (bet365, pornhub, vb.)
   - Eşleşirse LLM'e gitmez, doğrudan BLOCK döner
4. **İçerik çekme** — `httpx` ile HTML alınır, `trafilatura` ile ana metin ayıklanır
   - Erişilemezse (404/403/timeout) durum koduna göre WARN döner
5. **Cache kontrolü** — aynı URL + aynı içerik hash'i varsa cached sonuç döner
6. **İçerik ön filtresi** — metin içinde açık kumar/yetişkin kelime yoğunluğu var mı
7. **LLM sınıflandırma** — Ollama'ya sistem promptu + URL + içerik özeti gönderilir
   - JSON formatında `{category, decision, confidence, reasoning}` döner
8. **Risk skoru hesaplama** — kategori + güven skoruna göre 0-100 arası puan
9. **DB'ye yazma** — sonuç `url_analysis` tablosuna kaydedilir, `history` tablosuna log

---

## Teknoloji Stack'i

| Katman | Teknoloji |
|--------|-----------|
| Backend | Python 3.12, FastAPI, Uvicorn |
| ORM | SQLAlchemy |
| DB | PostgreSQL 16 |
| LLM | Ollama + qwen2.5:7b (OpenAI uyumlu API) |
| İçerik çekme | httpx, trafilatura, beautifulsoup4 |
| Domain parse | tldextract (offline mode) |
| Rate limit | slowapi |
| Frontend | Vanilla JS + HTML/CSS (glass-morphism tema) |
| Deploy | Docker Compose, Nginx, Cloudflare, Let's Encrypt |

---

## Kurulum

### Ön Gereksinimler

- Docker & Docker Compose
- Ollama (host makinede kurulu ve çalışıyor olmalı)
- Git

### Ollama Kurulumu

```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Modeli indir
ollama pull qwen2.5:7b

# Docker container'ından erişilebilmesi için 0.0.0.0'da dinlemesi lazım
sudo systemctl edit ollama
```

Açılan editöre şunu yaz:

```
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
```

Kaydet ve servisi yeniden başlat:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Test et:

```bash
curl http://localhost:11434/api/tags
```

### Projeyi Çalıştırma

```bash
# Repoyu klonla
git clone https://github.com/kuvetliabdulkadir/url-filter-ai.git
cd url-filter-ai

# Ortam değişkenlerini hazırla
cp .env.example .env
nano .env   # API_KEY, PUBLIC_READ_TOKEN vb. doldur

# Container'ları başlat
docker compose up --build -d

# Logları izle
docker compose logs -f app
```

Uygulama `http://localhost:8000` adresinde ayakta.

---

## Ortam Değişkenleri

`.env` dosyasında bulunması gerekenler:

```env
# Postgres
POSTGRES_USER=urlfilter
POSTGRES_PASSWORD=<güçlü_bir_şifre>
POSTGRES_DB=urlfilter
DATABASE_URL=postgresql://urlfilter:<şifre>@db:5432/urlfilter

# API güvenliği
API_KEY=<uzun_rastgele_string>
PUBLIC_READ_TOKEN=<frontend_için_ayrı_token>

# CORS
ALLOWED_ORIGINS=https://url.kuvetliabdulkadir.com,http://localhost:3000

# Ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_API_KEY=ollama

# Cache süresi (saat)
CACHE_TTL_HOURS=24
```

---

## API Endpoint'leri

### `POST /analyze`
URL'yi analiz eder.

**Request:**
```json
{ "url": "https://example.com" }
```

**Response:**
```json
{
  "url": "https://example.com/",
  "domain": "example.com",
  "category": "safe",
  "decision": "ALLOW",
  "confidence": 0.92,
  "risk_score": 8.4,
  "reasoning": "Kurumsal bir örnek sitedir, tehlikeli içerik yok.",
  "method": "llm",
  "cached": false,
  "llm_model": "qwen2.5:7b"
}
```

### `GET /list`
Tüm analiz geçmişini getirir. Query paramları:
- `category`: safe, social, gambling, adult
- `decision`: ALLOW, WARN, BLOCK
- `limit`, `offset`: sayfalama

### `DELETE /list/{id}`
Tek bir kaydı siler.

### `POST /list/bulk-delete`
```json
{ "ids": [1, 2, 3] }
```

### `GET /stats`
Toplam sayaçlar: analiz edilen, engellenen, cache hit.

### `GET /health`
Sağlık kontrolü, API key gerektirmez.

**Not:** Yazma endpoint'leri (`/analyze`, `DELETE /list/*`) same-origin veya `X-API-Key` gerektirir. Frontend, `PUBLIC_READ_TOKEN` ile sadece okuma yapabilir.

---

## Frontend

Single-page `static/index.html`. Ana bölümler:

- **Analiz kartı** — URL gir, "Analiz Et"'e bas
- **İstatistik kartları** — canlı sayaçlar
- **Son analiz kutusu** — kategori, karar, güven skoru, risk barları
- **Tüm Taramalar paneli** — filtre dropdown'ları, checkbox'lı çoklu seçim, tekil ✕ butonu, toplu sil butonu, kayıt tıklayınca detay modalı
- **Custom onay modalı** — `confirm()` yerine tema uyumlu popup

Cloudflare üzerinden yayında olduğu için `X-Frame-Options`, CSP başlıkları FastAPI middleware'de set edilmiş.

---

## Risk Skoru Hesaplama

Risk 0-100 arasında. Formül:

```
risk = base_score * confidence + 30 * (1 - confidence)
```

| Kategori | Base Score |
|----------|-----------|
| adult | 95 |
| gambling | 90 |
| social | 35 |
| safe | 5 |
| unknown | 30 |

**Neden bu formül?** LLM'in güveni düşükse (0.3 gibi) sonuç 30'a çekilir — "bilmiyorsam yüksek risk vermeyeyim" mantığı. Güven yüksekse (0.9) base'e yaklaşır.

**Özel durumlar:**
- HTTP 404 → risk 20 (site ölü, tehlike yok)
- HTTP 403 / timeout → risk 35 (bilinmiyor)
- Domain ön filtresinde BLOCK → risk 90 (kesin)

---

## Cache Mekanizması

Cache 3 aşamalı çalışır:

1. **URL match** — DB'de bu URL var mı?
2. **Hash match** — sayfa içeriği değişmiş mi (`sha256(text)`)
3. **TTL** — kayıt `CACHE_TTL_HOURS` saatten yeni mi?

Üçü de sağlanırsa LLM'e hiç gidilmez. Aksi halde yeniden analiz edilip DB güncellenir. Cache hit her seferinde `query_count` +1.

---

## Rate Limiting ve Güvenlik

- **slowapi** ile IP başına dakika bazlı sınır:
  - `/analyze` → 20/dk
  - `/list` (GET) → 30/dk
  - `/list/bulk-delete` → 10/dk
- **API key doğrulama** — `X-API-Key` header veya same-origin kontrolü
- **CORS** — sadece `.env`'deki origin'lere izin
- **Public read token** — frontend GET istekleri için ayrı, düşük yetkili token
- **CSP + X-Frame-Options** — clickjacking koruması

---

## Deploy (VPS + Nginx + Cloudflare)

Kısa versiyon:

1. VPS'te Docker + Ollama kur
2. Repoyu `/opt/url-filter-ai`'ya klonla
3. `.env` doldur, `docker compose up --build -d`
4. Nginx reverse proxy — `localhost:8000` → `url.example.com`
5. **Let's Encrypt için Cloudflare proxy'yi geçici kapat**, `certbot --nginx -d url.example.com`
6. Sertifika alınınca Cloudflare proxy'yi tekrar aç
7. Docker container'ı internete çıkabilmesi için bir bridge network'e bağla:
   ```bash
   docker network connect big-bear-n8n_default url-filter-ai-app-1
   ```


---

## Proje Yapısı

```
url-filter-ai/
├── app/
│   ├── main.py              # FastAPI uygulaması, endpoint'ler
│   ├── analyzer.py          # Ana analiz akışı
│   ├── content_fetcher.py   # httpx + trafilatura ile içerik çekme
│   ├── llm_client.py        # Ollama entegrasyonu, sistem promptu
│   ├── prefilter.py         # Domain ve kelime bazlı ön filtreler
│   ├── db.py                # SQLAlchemy modelleri
│   └── schemas.py           # Pydantic şemaları
├── static/
│   └── index.html           # Tek sayfa frontend
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

