import os
import socket
import httpx
import tldextract
from dotenv import load_dotenv

load_dotenv()

# .env'den ayarlar, yoksa varsayilan deger kullan
FETCH_TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "10"))
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", "500"))


def extract_domain(url: str) -> str:
    """url'den ana domain'i cikarir: https://www.bet365.co.uk/sports -> bet365.co.uk"""
    ext = tldextract.extract(url)
    if ext.suffix:
        return f"{ext.domain}.{ext.suffix}"
    return ext.domain


def check_dns(domain: str) -> bool:
    """domain gercekten var mi? dns'te cozumlenebiliyor mu?"""
    try:
        socket.setdefaulttimeout(3.0)
        socket.getaddrinfo(domain, None)
        return True
    except (socket.gaierror, socket.timeout):
        return False


def fetch_page_content(url: str) -> dict:
    """
    sayfanin icerigini ceker ve temiz metin olarak doner.
    
    doner: {
        "success": True/False,
        "text": "sayfa metni (ilk N kelime)",
        "title": "sayfa basligi",
        "error": "hata varsa aciklama"
    }
    """
    try:
        # sayfayi indir - tarayici gibi gorunmek icin user-agent ekliyoruz
        # bazi siteler bot oldugunu anlayinca icerik vermiyor
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = httpx.get(url, headers=headers, timeout=FETCH_TIMEOUT, follow_redirects=True)

        # sayfa bulunamadiysa (404, 500 vs.)
        if response.status_code >= 400:
            return {
                "success": False,
                "text": "",
                "title": "",
                "error": f"HTTP {response.status_code}"
            }

        html = response.text

        # trafilatura ile temiz metin cikar
        # ham html binlerce satir, bize sadece anlamli metin lazim
        try:
            from trafilatura import extract
            text = extract(html, include_comments=False, include_tables=False)
            if not text:
                text = ""
        except Exception:
            text = ""

        # html'den title cikar (basit yontem)
        title = ""
        if "<title>" in html.lower():
            start = html.lower().index("<title>") + 7
            end = html.lower().index("</title>", start)
            title = html[start:end].strip()

        # meta description cikar
        meta_desc = ""
        if 'name="description"' in html.lower():
            try:
                idx = html.lower().index('name="description"')
                content_start = html.lower().index('content="', idx) + 9
                content_end = html.index('"', content_start)
                meta_desc = html[content_start:content_end].strip()
            except (ValueError, IndexError):
                pass

        # hepsini birlestir: title + meta + icerik
        full_text = f"{title} {meta_desc} {text}".strip()

        # sadece ilk N kelimeyi al - llm'e gereksiz uzun metin gondermemek icin
        words = full_text.split()
        if len(words) > MAX_CONTENT_LENGTH:
            full_text = " ".join(words[:MAX_CONTENT_LENGTH])

        return {
            "success": True,
            "text": full_text,
            "title": title,
            "error": None
        }

    except httpx.TimeoutException:
        return {"success": False, "text": "", "title": "", "error": "sayfa zaman asimina ugradi"}
    except Exception as e:
        return {"success": False, "text": "", "title": "", "error": str(e)}