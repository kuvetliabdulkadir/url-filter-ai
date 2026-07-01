import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ollama, openai ile ayni formatta api sunuyor
# bu yuzden openai kutuphanesini kullaniyoruz ama adres ollama'ya gidiyor
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "ollama")  # ollama key istemez ama kutuphane zorunlu tutuyor

client = OpenAI(
    base_url=OLLAMA_BASE_URL,
    api_key=OLLAMA_API_KEY,
)

# llm'e gonderdigimiz talimat - ne yapmasini istedigimizi acikca soyluyoruz
# json formatinda cevap vermesini zorunlu tutuyoruz ki parse edebilelim
SYSTEM_PROMPT = """Sen bir URL icerik siniflandirma sistemisin.
Sana bir URL ve o sayfanin iceriginin bir bolumu verilecek.
Gorvin bu icerigi analiz edip siniflandirmak.

Kurallar:
1. Kategori su 4'ten biri OLMALI: social, gambling, adult, safe
2. Karar su 3'ten biri OLMALI: ALLOW, WARN, BLOCK
3. Karar mantigi:
   - safe -> ALLOW
   - social -> WARN
   - gambling -> BLOCK
   - adult -> BLOCK
4. Guven skoru 0.0 ile 1.0 arasi olmali
5. Kisa bir gerekce yaz (1-2 cumle)

SADECE asagidaki JSON formatinda cevap ver, baska hicbir sey yazma:
{"category": "...", "decision": "...", "confidence": 0.0, "reasoning": "..."}"""


def classify_with_llm(url: str, text: str) -> dict:
    """
    url ve sayfa metnini ollama'ya gonderip siniflandirma sonucu alir.
    
    doner: {
        "success": True/False,
        "category": "gambling",
        "decision": "BLOCK",
        "confidence": 0.85,
        "reasoning": "bahis sitesi",
        "model": "qwen2.5:7b",
        "error": None
    }
    """
    # llm'e gonderdigimiz mesaj - url + icerigin ilk bolumu
    user_message = f"URL: {url}\n\nSayfa icerigi:\n{text[:2000]}"

    try:
        response = client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,  # dusuk sicaklik = daha tutarli/belirli cevaplar
            timeout=30.0,     # ollama yavas olabilir, 30 sn bekle
        )

        # cevabi al
        raw = response.choices[0].message.content.strip()

        # json olarak parse et
        # bazen llm ```json ... ``` seklinde sarar, onu temizle
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)

        # beklenen alanlarin hepsi var mi kontrol et
        required = ["category", "decision", "confidence", "reasoning"]
        for field in required:
            if field not in result:
                return {
                    "success": False,
                    "category": "unknown",
                    "decision": "WARN",
                    "confidence": 0.0,
                    "reasoning": f"llm cevabinda '{field}' alani eksik",
                    "model": OLLAMA_MODEL,
                    "error": f"eksik alan: {field}",
                }

        # kategori ve karar gecerli mi kontrol et
        valid_categories = ["social", "gambling", "adult", "safe"]
        valid_decisions = ["ALLOW", "WARN", "BLOCK"]

        if result["category"] not in valid_categories:
            result["category"] = "unknown"
            result["decision"] = "WARN"

        if result["decision"] not in valid_decisions:
            result["decision"] = "WARN"

        return {
            "success": True,
            "category": result["category"],
            "decision": result["decision"],
            "confidence": float(result.get("confidence", 0.5)),
            "reasoning": result.get("reasoning", ""),
            "model": OLLAMA_MODEL,
            "error": None,
        }

    except json.JSONDecodeError:
        return {
            "success": False,
            "category": "unknown",
            "decision": "WARN",
            "confidence": 0.0,
            "reasoning": "llm gecerli json donmedi",
            "model": OLLAMA_MODEL,
            "error": f"json parse hatasi: {raw[:200]}",
        }
    except Exception as e:
        return {
            "success": False,
            "category": "unknown",
            "decision": "WARN",
            "confidence": 0.0,
            "reasoning": "llm baglantisi basarisiz",
            "model": OLLAMA_MODEL,
            "error": str(e),
        }