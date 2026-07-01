import re

# ---- evrensel kelimeler (her dilde ayni) ----
GAMBLING_UNIVERSAL = [
    "casino", "poker", "blackjack", "roulette", "slot", "baccarat",
    "bet365", "1xbet", "bwin", "betano", "parimatch","nesine", 
    "bilyoner", "misli", "tuttur", "iddaa", "sahadan"
]

ADULT_UNIVERSAL = [
    "porn", "xxx", "xnxx", "xvideos", "pornhub", "onlyfans",
    "brazzers", "xhamster", "redtube",
]

SOCIAL_UNIVERSAL = [
    "facebook", "instagram", "twitter", "tiktok", "snapchat",
    "reddit", "linkedin", "discord", "telegram", "whatsapp",
    "youtube", "twitch", "pinterest",
]

# ---- turkce kelimeler ----
GAMBLING_TR = [
    "kumar", "bahis", "canlı bahis", "iddaa", "tombala",
    "rulet", "şans oyunu", "ganyan","spor toto", "canlı iddaa", "at yarışı",
]

ADULT_TR = [
    "porno", "yetişkin", "erotik", "cinsel içerik",
]

# ---- ingilizce kelimeler ----
GAMBLING_EN = [
    "gambling", "betting", "sportsbook", "wager", "lottery",
    "jackpot", "bookmaker",
]

ADULT_EN = [
    "adult content", "nsfw", "explicit", "nude", "naked",
    "sex video", "adult video",
]

# ---- url pattern'lari (domain veya path'te gecen seyler) ----
RISKY_URL_PATTERNS = [
    r"\.xxx$",           # .xxx domain uzantisi
    r"/adult/",          # path'te adult gecen
    r"/bet/",            # path'te bet gecen
    r"/casino/",
    r"/poker/",
    r"/slot[s]?/",
]


def run_prefilter(url: str, text: str, domain: str) -> dict:
    """
    url, sayfa metni ve domain uzerinde keyword taramasi yapar.
    
    doner: {
        "matched": True/False,     - eslesme bulundu mu
        "category": "gambling",    - bulunan kategori (eslesme varsa)
        "decision": "BLOCK",       - onerilen karar
        "confidence": 0.95,        - ne kadar emin
        "keyword_hint": "casino",  - hangi kelime yakalandi
    }
    """
    # her seyi kucuk harfe cevir, boylece "CASINO" da "casino" da yakalanir
    url_lower = url.lower()
    text_lower = text.lower()
    domain_lower = domain.lower()

    # 1) url pattern kontrolu
    for pattern in RISKY_URL_PATTERNS:
        if re.search(pattern, url_lower):
            return {
                "matched": True,
                "category": "adult" if "xxx" in pattern or "adult" in pattern else "gambling",
                "decision": "BLOCK",
                "confidence": 0.9,
                "keyword_hint": f"url pattern: {pattern}",
            }

    # 2) domain kontrolu - domain'in kendisi bilinen bir site mi
    all_checks = [
        (GAMBLING_UNIVERSAL + GAMBLING_TR + GAMBLING_EN, "gambling", "BLOCK"),
        (ADULT_UNIVERSAL + ADULT_TR + ADULT_EN, "adult", "BLOCK"),
        (SOCIAL_UNIVERSAL, "social", "WARN"),
    ]

    for keywords, category, decision in all_checks:
        for kw in keywords:
            # domain'de geciyorsa yuksek guven
            if kw in domain_lower:
                return {
                    "matched": True,
                    "category": category,
                    "decision": decision,
                    "confidence": 0.95,
                    "keyword_hint": f"domain: {kw}",
                }

    # 3) icerik kontrolu - sayfa metninde geciyorsa
    for keywords, category, decision in all_checks:
        for kw in keywords:
            if kw in text_lower:
                # icerikten yakalamak domain'den yakalamaktan daha az guvenilir
                # cunku "casino" kelimesi bir haber sitesinde de gecebilir
                return {
                    "matched": True,
                    "category": category,
                    "decision": decision,
                    "confidence": 0.7,
                    "keyword_hint": f"content: {kw}",
                }

    # hicbir sey bulunamadi - llm'e gonder
    return {
        "matched": False,
        "category": None,
        "decision": None,
        "confidence": None,
        "keyword_hint": None,
    }