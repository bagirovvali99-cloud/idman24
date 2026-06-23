#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
İdman24 — Azərbaycan dilində canlı idman xəbərləri.

TƏK FAYL, QURAŞDIRMA YOXDUR:
  * Yalnız Python standart kitabxanasından istifadə edir (pip lazım deyil).
  * Xəbərləri SERVER tərəfində birbaşa saytlardan gətirir — proxy/CORS/VPN problemi YOXDUR.
  * Şəkil + tam mətn (oxucu öz səhifəndə oxuyur), kateqoriyalar, axtarış.
  * Diskdə keş saxlayır → növbəti açılış DƏRHAL, yalnız YENİ xəbərlər gəlir.
  * Öz xəbərlərini admin parolu ilə əlavə edirsən.

İŞƏ SALMAQ:  idman24.command faylına iki dəfə klikləyin
        VƏ YA Terminal-da:  python3 idman24_server.py
Sonra brauzer avtomatik açılır: http://127.0.0.1:8000
"""

import os, re, json, html, ssl, time, base64, mimetypes, threading, webbrowser, smtplib
import urllib.request
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
import xml.etree.ElementTree as ET

# ============================ AYARLAR ============================
# Hostinqdə PORT avtomatik verilir; lokalda 8000 işlədilir.
PORT = int(os.environ.get("PORT", 8000))
IS_HOSTED = bool(os.environ.get("PORT"))   # serverdə işləyirsə True
ADMIN_PASSWORD = os.environ.get("IDMAN24_ADMIN", "Baku1234")  # <-- parol (hostinqdə dəyişən kimi qoyun)
REFRESH_MINUTES = 8
BASE = os.path.dirname(os.path.abspath(__file__))
# Daimi məlumat qovluğu: hostinqdə DATA_DIR=/var/data (Persistent Disk) qoyun;
# lokalda bu fayl qovluğunda saxlanılır. Belə olduqda redeploy-da xəbərlər/şərhlər İTMİR.
DATA_DIR = os.environ.get("DATA_DIR", BASE)
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = BASE
CACHE_FILE = os.path.join(DATA_DIR, "idman24_cache.json")
MANUAL_FILE = os.path.join(DATA_DIR, "idman24_manual.json")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
COMMENTS_FILE = os.path.join(DATA_DIR, "idman24_comments.json")
STATS_FILE = os.path.join(DATA_DIR, "idman24_stats.json")
CONTACTS_FILE = os.path.join(DATA_DIR, "idman24_contacts.json")
# Əlaqə mesajları üçün e-poçt (hostinqdə dəyişən kimi qoyulur, kodda görünmür):
GMAIL_USER = os.environ.get("GMAIL_USER", "")            # göndərən gmail
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")  # gmail "app password"
CONTACT_TO = os.environ.get("CONTACT_TO", GMAIL_USER)    # mesajların gedəcəyi ünvan

FEEDS = [
    {"name": "APA Sport",    "url": "https://apasport.az/rss",    "site": "apasport.az", "sport_only": False},
    {"name": "İdman Xəbər",  "url": "https://idmanxeber.az/feed", "site": "idmanxeber.az", "sport_only": False},
    {"name": "Report İdman", "url": "https://report.az/rss",      "site": "report.az", "sport_only": True},
    # Əlavə ümumi mənbə:
    {"name": "Oxu.az İdman", "url": "https://oxu.az/rss",         "site": "oxu.az", "sport_only": True},
    # Federasiya RSS lentləri (yalnız xəbər postları, menyu səhifələri yox):
    {"name": "Güləş Federasiyası", "url": "https://awf.az/xeberler/feed/", "site": "awf.az",
     "sport_only": False, "force_cat": "Döyüş İdmanı"},
    {"name": "F-1.az", "url": "https://www.f-1.az/category/formula-1/xeberler/feed/", "site": "f-1.az",
     "sport_only": False, "force_cat": "Formula 1"},
]

# Federasiya saytları (RSS yoxdur — xəbər səhifəsi birbaşa oxunur)
SCRAPERS = [
    {"name": "Cüdo Federasiyası",      "url": "https://www.judo.az/News",  "site": "judo.az",
     "category": "Cüdo",       "pat": r'https://(?:www\.)?judo\.az/News/News/[A-Za-z0-9\-]+'},
    {"name": "Gimnastika Federasiyası","url": "https://agf.az/az/news/",    "site": "agf.az",
     "category": "Gimnastika", "pat": r'https://agf\.az/az/news/(?!archive|page/)[A-Za-z0-9\-]+\d+'},
    {"name": "Milli Olimpiya Komitəsi", "url": "https://www.olympic.az/articles", "site": "olympic.az",
     "category": "", "pat": r'https://www\.olympic\.az/news/[A-Za-z0-9\-]+'},
]

CAT_RULES = [
    ("Futbol", ["futbol","premyer","çempionlar liqası","uefa","fifa","dç-","dç ","transfer","qarabağ","neftçi","səbail","sabah","zirə","turan","araz","kəpəz","messi","ronaldo","real madrid","barselona","la liqa","premyer liqa","penalti","hetrik","qapıçı","tottenhem","arsenal","çelsi","mançester","liverpul","yuventus","bavariya","psj","atletiko"]),
    ("Basketbol", ["basketbol","nba","evroliqa","basket"]),
    ("Voleybol", ["voleybol"]),
    ("Döyüş İdmanı", ["güləş","güləşçi","sərbəst güləş","yunan-roma","pəhləvan","boks","boksçu","boksçumuz","nokaut","ufc","mma","karate","karateçi","taekvondo","döyüş","döyüşçü","ağır atletika","ştanqaçı","fiziyev","nurməhəmmədov","kikboks","sambo","samboçu"]),
    ("Cüdo", ["cüdo","cudo","judo","cüdoçu","cüdoçular","cüdo federasiyası","qrand slem","qran-slem"]),
    ("Gimnastika", ["gimnastika","gimnast","akrobatika","batut","bədii gimnastika","aerobika","trampolin"]),
    ("Formula 1", ["formula","f1","qran-pri","ferrari","ferstappen","hamilton"]),
    ("Şahmat", ["şahmat","qrossmeyster","qarpov","karlsen"]),
]
SPORT_HINTS = [w for _, ws in CAT_RULES for w in ws] + \
    ["idman","matç","komanda","klub","stadion","çempion","turnir","medal","oyunçu","məşqçi","yarış","kubok","final","heç-heçə","məğlub","qələbə"]
CATEGORIES = ["Hamısı"] + [c for c, _ in CAT_RULES] + ["Digər"]
KEEP_MAX = 600

_SSL = ssl.create_default_context(); _SSL.check_hostname = False; _SSL.verify_mode = ssl.CERT_NONE
# Real brauzer kimi görünmək (bəzi saytlar adi sorğuları 403 ilə bloklayır)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "az,en;q=0.9,ru;q=0.8",
    "Referer": "https://www.google.com/",
    "Connection": "close",
}

# ============================ KÖMƏKÇİLƏR ============================
def http_get(url, timeout=12):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
        raw = r.read()
    enc = "utf-8"
    ct = r.headers.get("Content-Type", "")
    m = re.search(r"charset=([\w-]+)", ct)
    if m:
        enc = m.group(1)
    try:
        return raw.decode(enc, "replace")
    except Exception:
        return raw.decode("utf-8", "replace")

def strip_html(s):
    if not s: return ""
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()

def norm_title(t):
    # Başlığı müqayisə üçün sadələşdir + canlı yeniləmə/video sonluqlarını sil
    s = re.sub(r"\W+", "", (t or "").lower(), flags=re.U)
    s = re.sub(r"(yenilənir|yenilənib|yenilənmişdir|yenilndi|yenilnir|yenilnib|canlı|video|foto)+$", "", s)
    return s

_CAT_MAP = {c: ws for c, ws in CAT_RULES}
# Spesifik fənləri Futboldan ƏVVƏL yoxla (ümumi "beynəlxalq oyunlar" etiketi futbola yönləndirməsin)
# Cüdo siyahıda yoxdur — yalnız judo.az-dan. Tennis/Boks/Olimpiya tabları silindi.
_DETECT_ORDER = ["Gimnastika", "Döyüş İdmanı", "Basketbol",
                 "Voleybol", "Formula 1", "Şahmat", "Futbol"]

def detect_cat(title, feed_cat):
    t = (title + " " + (feed_cat or "")).lower()
    for c in _DETECT_ORDER:
        if any(w in t for w in _CAT_MAP.get(c, [])):
            return c
    return "Digər"

def to_iso(date_str):
    if date_str:
        try:
            return parsedate_to_datetime(date_str).astimezone(timezone.utc).isoformat()
        except Exception:
            try:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
            except Exception:
                pass
    return datetime.now(timezone.utc).isoformat()

def text_of(el):
    return (el.text or "").strip() if el is not None else ""

def local(tag):
    return tag.rsplit("}", 1)[-1]

# ============================ LENT EMALI ============================
def parse_feed(xml_str, feed):
    out = []
    try:
        root = ET.fromstring(xml_str.encode("utf-8"))
    except Exception:
        try:
            root = ET.fromstring(re.sub(r"&(?!amp;|lt;|gt;|quot;|#)", "&amp;", xml_str).encode("utf-8"))
        except Exception:
            return out
    nodes = [e for e in root.iter() if local(e.tag) in ("item", "entry")]
    for e in nodes[:120]:
        title = link = desc = cat = date = ""
        img = ""
        for ch in e:
            t = local(ch.tag)
            if t == "title": title = strip_html(ch.text)
            elif t == "link":
                link = (ch.text or "").strip() or ch.attrib.get("href", "")
            elif t in ("description", "summary", "encoded"): desc = desc or (ch.text or "")
            elif t == "category": cat = cat or strip_html(ch.text)
            elif t in ("pubDate", "published", "updated"): date = date or (ch.text or "")
            elif t in ("content",):
                desc = desc or (ch.text or "")
            elif t in ("enclosure", "thumbnail", "content") and ch.attrib.get("url"):
                if not img and "image" in (ch.attrib.get("type", "") + t).lower() or t == "thumbnail":
                    img = ch.attrib.get("url", "")
        if not title:
            continue
        if feed.get("sport_only"):
            hay = (title + " " + cat).lower()
            if not any(h in hay for h in SPORT_HINTS):
                continue
        if not img:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc or "")
            if m: img = m.group(1)
        out.append({
            "id": "rss_" + str(abs(hash(link or title))),
            "title": title, "summary": strip_html(desc)[:300], "body": "",
            "category": feed.get("force_cat") or detect_cat(title, cat), "image": img,
            "author": feed["name"], "link": link, "source": feed["name"],
            "site": feed["site"], "date": to_iso(date), "manual": False,
        })
    return out

# ============================ FEDERASİYA SAYTLARI (scrape) ============================
AZ_MONTHS = {"yanvar":1,"fevral":2,"mart":3,"aprel":4,"may":5,"iyun":6,
             "iyul":7,"avqust":8,"sentyabr":9,"oktyabr":10,"noyabr":11,"dekabr":12}
_CAT_LABELS = ["Əsas xəbərlər","Beynəlxalq turnirlər","Yerli turnirlər","Müsahibələr","Müsahibə","Digər"]

def parse_az_date(text):
    m = re.search(r"(\d{1,2})\s+(" + "|".join(AZ_MONTHS) + r")\s*,?\s*(\d{4})", text, re.I)
    if m:
        try:
            return datetime(int(m.group(3)), AZ_MONTHS[m.group(2).lower()], int(m.group(1)),
                            tzinfo=timezone.utc).isoformat()
        except Exception:
            pass
    return datetime.now(timezone.utc).isoformat()

def clean_fed_title(text):
    t = re.sub(r"\s+", " ", strip_html(text)).strip()
    iso = parse_az_date(t)
    t = t.replace("Ətraflı", " ")
    # tarixi (+ istəyə bağlı saatı) hər yerdən sil: "19 iyun 2026 - 19:55" və ya "19 iyun 2026"
    t = re.sub(r"\d{1,2}\s+(?:" + "|".join(AZ_MONTHS) + r")\s*,?\s*\d{4}(?:\s*-\s*\d{1,2}:\d{2})?",
               " ", t, flags=re.I)
    t = re.sub(r"^\s*-?\s*\d{1,2}:\d{2}\s*", " ", t)              # qalıq saat
    for lbl in _CAT_LABELS:                                       # kateqoriya etiketi
        if t.strip().startswith(lbl):
            t = t.strip()[len(lbl):]
    return re.sub(r"\s+", " ", t).strip(" -–·"), iso

def scrape_one(sc):
    out, errors = [], []
    try:
        h = http_get(sc["url"])
        # Bütün linkləri tut (nisbi VƏ tam), sonra mütləqə çevirib pattern-lə süz
        rx = re.compile(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', re.I | re.S)
        pat = re.compile(sc["pat"])
        seen = set()
        for href, inner in rx.findall(h):
            full = abs_url(sc["url"], href)
            if not pat.search(full) or full in seen:
                continue
            seen.add(full)
            title, iso = clean_fed_title(inner)
            if len(title) < 8:
                continue
            out.append({
                "id": "scr_" + str(abs(hash(full))),
                "title": title[:200], "summary": "", "body": "",
                "category": sc["category"] or detect_cat(title, ""), "image": "",
                "author": sc["name"], "link": full, "source": sc["name"],
                "site": sc["site"], "date": iso, "manual": False,
            })
            if len(out) >= 25:
                break
    except Exception as e:
        errors.append(f"{sc['name']}: {e}")
    return out, errors

# ============================ KEŞ / DURUM ============================
_lock = threading.Lock()
LIVE = []
ENRICH = {}     # url -> {"image":..., "body":...}
UPDATED = None

def load_cache():
    global LIVE, ENRICH, UPDATED
    try:
        if os.path.exists(CACHE_FILE):
            d = json.load(open(CACHE_FILE, encoding="utf-8"))
            LIVE = d.get("items", []); UPDATED = d.get("updated")
            ENRICH = {}   # köhnə mətn/şəkil keşini sıfırla — təmiz məntiqlə yenidən çəkilsin
            for it in LIVE:
                if "judo.az" in it.get("link", ""):
                    it["image"] = ""        # judo şəkillərini sıfırla ki, düzgün məntiqlə yenidən çəkilsin
                elif it.get("image"):
                    it["image"] = abs_url(it.get("link", ""), it["image"])
            # Köhnə/yararsız scraper qeydlərini təmizlə (məs. səhv güləş scrape-i)
            valid = {s["site"] for s in SCRAPERS}
            LIVE = [it for it in LIVE
                    if not (it.get("id", "").startswith("scr_") and it.get("site") not in valid)]
    except Exception as e:
        print("[load_cache]", e)

def save_cache():
    try:
        with _lock:
            d = {"items": LIVE[:KEEP_MAX], "enrich": ENRICH, "updated": UPDATED}
        json.dump(d, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        print("[save_cache]", e)

def load_manual():
    try:
        if os.path.exists(MANUAL_FILE):
            return json.load(open(MANUAL_FILE, encoding="utf-8"))
    except Exception:
        pass
    return []

def save_manual(items):
    json.dump(items, open(MANUAL_FILE, "w", encoding="utf-8"), ensure_ascii=False)

# ---- Şərhlər ----
_clock = threading.Lock()
COMMENTS = {}

def load_comments():
    global COMMENTS
    try:
        if os.path.exists(COMMENTS_FILE):
            COMMENTS = json.load(open(COMMENTS_FILE, encoding="utf-8")) or {}
    except Exception as e:
        print("[load_comments]", e); COMMENTS = {}

def save_comments():
    try:
        json.dump(COMMENTS, open(COMMENTS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        print("[save_comments]", e)

# ---- Statistika (oxunma/paylaşım) — yalnız admin görür ----
_slock = threading.Lock()
STATS = {}

def load_stats():
    global STATS
    try:
        if os.path.exists(STATS_FILE):
            STATS = json.load(open(STATS_FILE, encoding="utf-8")) or {}
    except Exception as e:
        print("[load_stats]", e); STATS = {}

def save_stats():
    try:
        json.dump(STATS, open(STATS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        print("[save_stats]", e)

# ---- Əlaqə mesajları ----
_ctlock = threading.Lock()
CONTACTS = []

def load_contacts():
    global CONTACTS
    try:
        if os.path.exists(CONTACTS_FILE):
            CONTACTS = json.load(open(CONTACTS_FILE, encoding="utf-8")) or []
    except Exception as e:
        print("[load_contacts]", e); CONTACTS = []

def save_contacts():
    try:
        json.dump(CONTACTS[-500:], open(CONTACTS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        print("[save_contacts]", e)

def send_contact_email(name, phone, msg, img_bytes=None, ext="jpg"):
    if not (GMAIL_USER and GMAIL_APP_PASSWORD and CONTACT_TO):
        return False
    try:
        em = EmailMessage()
        em["From"] = GMAIL_USER
        em["To"] = CONTACT_TO
        em["Subject"] = f"İdman24 əlaqə — {name or 'Anonim'}"
        em.set_content(f"Yeni əlaqə mesajı (idman24.com)\n\nAd: {name or '-'}\n"
                       f"Telefon: {phone or '-'}\n\nMesaj:\n{msg or '-'}")
        if img_bytes:
            sub = ext.lower().replace("jpg", "jpeg")
            em.add_attachment(img_bytes, maintype="image", subtype=sub, filename=f"foto.{ext}")
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=15) as s:
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(em)
        return True
    except Exception as e:
        print("[email]", e); return False

# ============================ ZƏNGİNLƏŞDİRMƏ (şəkil + mətn) ============================
def _chunks(t, n):
    out = []
    while t:
        if len(t) <= n:
            out.append(t); break
        cut = t.rfind("\n", 0, n)
        if cut < n * 0.5:
            cut = t.rfind(" ", 0, n)
        if cut <= 0:
            cut = n
        out.append(t[:cut]); t = t[cut:]
    return out

_TRC = {}
def translate_text(text, tl):
    text = (text or "").strip()
    if not text:
        return ""
    tl = re.sub(r"[^a-zA-Z\-]", "", tl)[:5] or "en"
    key = tl + "|" + str(abs(hash(text)))
    if key in _TRC:
        return _TRC[key]
    parts = []
    for ch in _chunks(text, 1500):
        try:
            url = ("https://translate.googleapis.com/translate_a/single?client=gtx"
                   "&sl=auto&tl=" + tl + "&dt=t&q=" + quote(ch))
            data = json.loads(http_get(url, timeout=12))
            parts.append("".join(seg[0] for seg in data[0] if seg and seg[0]))
        except Exception:
            parts.append(ch)
    res = "".join(parts)
    if len(_TRC) > 2000:
        _TRC.clear()
    _TRC[key] = res
    return res

def og_image(h):
    for pat in [r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
                r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)']:
        m = re.search(pat, h, re.I)
        if m and m.group(1).strip():
            return m.group(1).strip()
    # og:image yoxdursa — səhifədəki ilk əsl məzmun şəklini götür (loqo/ikon istisna)
    for mm in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', h, re.I):
        src = mm.group(1)
        if re.search(r'(logo|icon|favicon|sprite|placeholder|avatar|banner|\.svg)', src, re.I):
            continue
        return src
    return ""

def content_img(h):
    # Səhifə gövdəsindəki əsl məqalə şəkli (loqo/tema/ikon istisna) — bəzi saytlarda og:image qırıqdır
    cands = []
    for mm in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', h, re.I):
        src = mm.group(1)
        if re.search(r'(logo|icon|favicon|sprite|placeholder|avatar|banner|\.svg'
                     r'|/img/|/assets/|/front/|/static/|/theme/|/template)', src, re.I):
            continue
        cands.append(src)
    if not cands:
        return ""
    for s in cands:   # əsl məzmun qovluqlarına üstünlük ver
        if re.search(r'(upload|file|media|custom|content|news|photo|image|wp-content)', s, re.I):
            return s
    return cands[0]

def og_desc(h):
    m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)', h, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']og:description', h, re.I)
    if not m:
        m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', h, re.I)
    return strip_html(html.unescape(m.group(1))) if m else ""

# YALNIZ məqalənin sonundakı bloklar (menyu/başlıqda görünməyən sözlər)
_STOP_RE = re.compile(r'(Oxşar xəbər|köşə yaz|Paylaş\s*:|Oxşar xəbərlər)', re.I)
_SKIP_P = re.compile(r"(?i)^(reklam|abunə|paylaş|copyright|©|mobil tətbiq|tətbiqimiz|yüklə|app store|google play|bütün xəbər|son xəbər|bizi izlə|apa group|müəllif hüquq)")

def body_from_p(h):
    cut = _STOP_RE.search(h)
    block = h[:cut.start()] if cut else h
    m = re.search(r"(?is)<article[^>]*>(.*?)</article>", block)
    if m:
        block = m.group(1)
    cleaned = []
    for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", block):
        t = strip_html(p)
        if len(t) > 30 and not _SKIP_P.match(t):
            cleaned.append(t)
    return "\n\n".join(cleaned[:25])[:6000]

def extract_body(h):
    return body_from_p(h) or og_desc(h)

def abs_url(base, img):
    if not img:
        return ""
    if img.startswith("http"):
        return img
    p = urlparse(base)
    if img.startswith("//"):
        return p.scheme + ":" + img
    if img.startswith("/"):
        return f"{p.scheme}://{p.netloc}{img}"
    return f"{p.scheme}://{p.netloc}/{img}"

def enrich(url):
    if not url: return {"image": "", "body": ""}
    with _lock:
        if url in ENRICH: return ENRICH[url]
    try:
        h = http_get(url, timeout=12)
        fed = any(s in url for s in ("judo.az", "agf.az", "olympic.az"))
        raw_img = content_img(h) if "judo.az" in url else (og_image(h) or content_img(h))
        # Federasiya saytlarında <p> qarışıqdır → og:description; digərlərində tam <p> mətni
        body = (og_desc(h) or body_from_p(h)) if fed else (body_from_p(h) or og_desc(h))
        data = {"image": abs_url(url, raw_img), "body": body}
    except Exception:
        data = {"image": "", "body": ""}
    with _lock:
        ENRICH[url] = data
    return data

def background_enrich():
    with _lock:
        targets = [i["link"] for i in LIVE
                   if i["link"] and not i.get("image") and i["link"] not in ENRICH][:600]
    if not targets: return
    with ThreadPoolExecutor(max_workers=10) as pool:
        pool.map(enrich, targets)
    # şəkilləri elementlərə tətbiq et
    with _lock:
        for it in LIVE:
            e = ENRICH.get(it["link"])
            if e and e.get("image") and not it.get("image"):
                it["image"] = e["image"]
    save_cache()

# ============================ FETCH (yalnız yeni) ============================
def _feed_safe(f):
    try:
        return parse_feed(http_get(f["url"]), f)
    except Exception as e:
        print("[fetch]", f["name"], e); return []

def _scrape_safe(s):
    items, errs = scrape_one(s)
    for e in errs: print("[scrape]", e)
    return items

def fetch_all():
    global LIVE, UPDATED
    fetched = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        for r in pool.map(_feed_safe, FEEDS):
            fetched += r
        for r in pool.map(_scrape_safe, SCRAPERS):
            fetched += r
    with _lock:
        have = {i["id"] for i in LIVE}
        added = 0
        for it in fetched:
            if it["id"] not in have:
                LIVE.append(it); have.add(it["id"]); added += 1
        LIVE.sort(key=lambda x: x["date"], reverse=True)
        # Eyni xəbər müxtəlif mənbələrdə: başlığa görə təkrarları sil (ən yenisini saxla)
        seen, deduped = set(), []
        for it in LIVE:
            k = norm_title(it["title"])
            if k and k in seen:
                continue
            seen.add(k); deduped.append(it)
        LIVE = deduped
        del LIVE[KEEP_MAX:]
        for it in LIVE:  # mövcud şəkilləri saxla
            e = ENRICH.get(it["link"])
            if e and e.get("image") and not it.get("image"):
                it["image"] = e["image"]
        UPDATED = datetime.now(timezone.utc).isoformat()
    if fetched:
        save_cache()
        print(f"  {len(fetched)} xəbər yoxlanıldı, {added} yeni.")
    background_enrich()

def refresher():
    while True:
        try: fetch_all()
        except Exception as e: print("[refresher]", e)
        time.sleep(REFRESH_MINUTES * 60)

# ============================ HTTP HANDLER ============================
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/news":
            with _lock:
                items = load_manual() + LIVE
                items.sort(key=lambda x: (not x.get("manual", False),))
                return self._send(200, {"updated": UPDATED, "categories": CATEGORIES, "items": items})
        if u.path == "/api/article":
            url = parse_qs(u.query).get("url", [""])[0]
            return self._send(200, enrich(url))
        if u.path == "/api/comments":
            aid = parse_qs(u.query).get("id", [""])[0]
            with _clock:
                return self._send(200, {"comments": COMMENTS.get(aid, [])})
        if u.path.startswith("/uploads/"):
            fn = os.path.basename(u.path)
            fp = os.path.join(UPLOAD_DIR, fn)
            if os.path.isfile(fp):
                ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
                return self._send(200, open(fp, "rb").read(), ctype)
            return self._send(404, {"error": "not found"})
        return self._send(404, {"error": "not found"})

    @staticmethod
    def _save_image(data_url):
        # "data:image/jpeg;base64,...." -> faylı saxla, /uploads/... qaytar
        try:
            if not data_url.startswith("data:"):
                return ""
            header, b64 = data_url.split(",", 1)
            m = re.search(r"data:image/([\w.+-]+)", header)
            ext = (m.group(1) if m else "jpg").lower().replace("jpeg", "jpg").replace("svg+xml", "svg")
            fname = f"{int(time.time()*1000)}.{ext}"
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
                f.write(base64.b64decode(b64))
            return "/uploads/" + fname
        except Exception as e:
            print("[upload]", e); return ""

    def do_POST(self):
        u = urlparse(self.path)
        ln = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(ln) or b"{}")
        if u.path == "/api/comments":
            aid = (body.get("id") or "").strip()
            text = (body.get("text") or "").strip()[:1000]
            name = ((body.get("name") or "").strip()[:40]) or "Anonim"
            if not aid or not text:
                return self._send(400, {"ok": False, "error": "Şərh boş ola bilməz"})
            with _clock:
                COMMENTS.setdefault(aid, []).append(
                    {"name": name, "text": text, "date": datetime.now(timezone.utc).isoformat()})
                COMMENTS[aid] = COMMENTS[aid][-300:]
                save_comments()
            return self._send(200, {"ok": True})
        if u.path == "/api/track":
            aid = (body.get("id") or "").strip()
            typ = body.get("type")
            if aid and typ in ("view", "share"):
                with _slock:
                    s = STATS.setdefault(aid, {"views": 0, "shares": 0, "title": ""})
                    if body.get("title"):
                        s["title"] = (body.get("title") or "")[:160]
                    s["views" if typ == "view" else "shares"] += 1
                    save_stats()
            return self._send(200, {"ok": True})
        if u.path == "/api/stats":
            if body.get("password") != ADMIN_PASSWORD:
                return self._send(401, {"ok": False, "error": "Parol yanlışdır"})
            with _slock:
                items = [{"id": k, "title": v.get("title", ""),
                          "views": v.get("views", 0), "shares": v.get("shares", 0)}
                         for k, v in STATS.items()]
            items.sort(key=lambda x: x["views"], reverse=True)
            return self._send(200, {"ok": True,
                "totalViews": sum(i["views"] for i in items),
                "totalShares": sum(i["shares"] for i in items),
                "items": items[:100]})
        if u.path == "/api/contact":
            name = (body.get("name") or "").strip()[:80]
            phone = (body.get("phone") or "").strip()[:40]
            msg = (body.get("message") or "").strip()[:3000]
            if not (phone or msg):
                return self._send(400, {"ok": False, "error": "Mesaj və ya nömrə yazın"})
            du = body.get("image_data") or ""
            img_path = self._save_image(du)
            rec = {"name": name, "phone": phone, "message": msg, "image": img_path,
                   "date": datetime.now(timezone.utc).isoformat()}
            with _ctlock:
                CONTACTS.append(rec); save_contacts()
            img_bytes, ext = None, "jpg"
            if du.startswith("data:"):
                try:
                    hdr, b64 = du.split(",", 1)
                    mm = re.search(r"data:image/([\w.+-]+)", hdr)
                    ext = (mm.group(1) if mm else "jpg").replace("jpeg", "jpg")
                    img_bytes = base64.b64decode(b64)
                except Exception:
                    img_bytes = None
            threading.Thread(target=send_contact_email,
                             args=(name, phone, msg, img_bytes, ext), daemon=True).start()
            return self._send(200, {"ok": True})
        if u.path == "/api/contacts":
            if body.get("password") != ADMIN_PASSWORD:
                return self._send(401, {"ok": False, "error": "Parol yanlışdır"})
            with _ctlock:
                return self._send(200, {"ok": True, "items": list(reversed(CONTACTS))[:200]})
        if u.path == "/api/translate":
            txt = (body.get("text") or "")[:6000]
            tl = body.get("tl") or "en"
            return self._send(200, {"text": translate_text(txt, tl)})
        if u.path == "/api/login":
            return self._send(200, {"ok": body.get("password") == ADMIN_PASSWORD})
        if u.path == "/api/refresh":
            fetch_all()
            return self._send(200, {"ok": True, "updated": UPDATED})
        if u.path == "/api/article/add":
            if body.get("password") != ADMIN_PASSWORD:
                return self._send(401, {"ok": False, "error": "Parol yanlışdır"})
            if not body.get("title"):
                return self._send(400, {"ok": False, "error": "Başlıq tələb olunur"})
            # Yüklənmiş şəkli saxla; yoxdursa, ünvan (URL) varsa onu işlət
            img = self._save_image(body.get("image_data") or "") or (body.get("image") or "").strip()
            items = load_manual()
            items.insert(0, {
                "id": "man_" + str(int(time.time() * 1000)),
                "title": body["title"].strip(), "summary": (body.get("summary") or "").strip(),
                "body": (body.get("body") or "").strip(), "category": body.get("category") or "Digər",
                "image": img, "author": (body.get("author") or "Redaksiya").strip(),
                "link": (body.get("link") or "").strip(), "source": "Redaksiya", "site": "",
                "date": datetime.now(timezone.utc).isoformat(), "manual": True,
            })
            save_manual(items)
            return self._send(200, {"ok": True})
        if u.path == "/api/article/edit":
            if body.get("password") != ADMIN_PASSWORD:
                return self._send(401, {"ok": False, "error": "Parol yanlışdır"})
            if not body.get("title"):
                return self._send(400, {"ok": False, "error": "Başlıq tələb olunur"})
            items = load_manual()
            found = False
            for it in items:
                if it.get("id") == body.get("id"):
                    it["title"] = body["title"].strip()
                    it["summary"] = (body.get("summary") or "").strip()
                    it["body"] = (body.get("body") or "").strip()
                    it["category"] = body.get("category") or it.get("category", "Digər")
                    it["author"] = (body.get("author") or "Redaksiya").strip()
                    it["link"] = (body.get("link") or "").strip()
                    newimg = self._save_image(body.get("image_data") or "")
                    if newimg:                       # yeni şəkil yükləndisə əvəz et
                        it["image"] = newimg
                    found = True
                    break
            if not found:
                return self._send(404, {"ok": False, "error": "Xəbər tapılmadı"})
            save_manual(items)
            return self._send(200, {"ok": True})
        if u.path == "/api/article/delete":
            if body.get("password") != ADMIN_PASSWORD:
                return self._send(401, {"ok": False, "error": "Parol yanlışdır"})
            items = [i for i in load_manual() if i["id"] != body.get("id")]
            save_manual(items)
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})

# ============================ START ============================
def main():
    load_cache()
    load_comments()
    load_stats()
    load_contacts()
    print("\n  İdman24 başlayır...")
    if LIVE: print(f"  {len(LIVE)} xəbər keşdən dərhal yükləndi.")
    threading.Thread(target=refresher, daemon=True).start()
    host = "0.0.0.0" if IS_HOSTED else "127.0.0.1"
    if IS_HOSTED:
        print(f"  Server hostinqdə işləyir, port {PORT}")
    else:
        url = f"http://127.0.0.1:{PORT}"
        print(f"  Hazırdır: {url}\n  Admin parolu: {ADMIN_PASSWORD}\n  (Dayandırmaq: Ctrl+C)\n")
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    ThreadingHTTPServer((host, PORT), H).serve_forever()


# ============================ SƏHİFƏ (UI) ============================
PAGE = r"""<!DOCTYPE html><html lang="az"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>İdman24 — Canlı İdman Xəbərləri</title>
<style>
:root{--bg:#0a0e17;--bg2:#0f1626;--card:#141d30;--card2:#1a2540;--line:#22304d;--txt:#eaf0fb;--muted:#8da2c5;--accent:#00e6a8;--accent2:#ff3d71;--gold:#ffc24b;--radius:16px}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,-apple-system,Roboto,Arial,sans-serif;background:var(--bg);color:var(--txt);line-height:1.5}
a{color:inherit;text-decoration:none}
::-webkit-scrollbar{height:8px;width:8px}::-webkit-scrollbar-thumb{background:#2a3a5c;border-radius:8px}
header{position:sticky;top:0;z-index:50;background:rgba(10,14,23,.92);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.bar{max-width:1240px;margin:0 auto;display:flex;align-items:center;gap:18px;padding:14px 20px}
.logo{display:flex;align-items:center;gap:10px;font-weight:900;font-size:26px;letter-spacing:-.5px;cursor:pointer}
.logo .dot{color:var(--accent)}.logo .z{background:linear-gradient(135deg,var(--accent),#36a0ff);-webkit-background-clip:text;background-clip:text;color:transparent}
.ball{width:34px;height:34px;border-radius:50%;background:radial-gradient(circle at 32% 30%,#fff 0 18%,var(--accent) 19% 100%);box-shadow:0 0 18px rgba(0,230,168,.5);animation:spin 9s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.search{flex:1;max-width:420px;margin-left:auto;position:relative}
.search input{width:100%;background:var(--card);border:1px solid var(--line);color:var(--txt);padding:11px 14px 11px 38px;border-radius:30px;outline:none;font-size:14px}
.search input:focus{border-color:var(--accent)}.search svg{position:absolute;left:12px;top:11px;opacity:.6}
.admin-link{background:var(--accent2);color:#fff;padding:9px 16px;border-radius:30px;font-weight:700;font-size:13px;white-space:nowrap;cursor:pointer;border:none}
.admin-link:hover{filter:brightness(1.1)}
.ticker{background:linear-gradient(90deg,var(--accent2),#b3204d);overflow:hidden;white-space:nowrap;font-size:13px;font-weight:600}
.ticker .wrap{display:inline-block;padding:7px 0;animation:slide 38s linear infinite}
.ticker b{background:#fff;color:var(--accent2);padding:2px 9px;border-radius:4px;margin:0 14px;font-size:11px;letter-spacing:.5px}
.ticker span{margin-right:42px;opacity:.95}@keyframes slide{from{transform:translateX(0)}to{transform:translateX(-50%)}}
nav{position:sticky;top:64px;z-index:40;background:var(--bg2);border-bottom:1px solid var(--line)}
.tabs{max-width:1240px;margin:0 auto;display:flex;gap:6px;padding:10px 20px;overflow-x:auto}
.tab{padding:8px 16px;border-radius:30px;background:transparent;border:1px solid var(--line);color:var(--muted);font-size:14px;font-weight:600;cursor:pointer;white-space:nowrap;transition:.2s}
.tab:hover{color:var(--txt);border-color:#3a4d72}.tab.active{background:var(--accent);color:#04231a;border-color:var(--accent)}
main{max-width:1240px;margin:0 auto;padding:24px 20px 60px}
.meta{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:18px;color:var(--muted);font-size:13px}
.refresh{background:var(--card);border:1px solid var(--line);color:var(--txt);padding:7px 14px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:600}
.refresh:hover{border-color:var(--accent)}
.hero{display:grid;grid-template-columns:1.6fr 1fr;gap:16px;margin-bottom:26px}
.hero-main{position:relative;border-radius:var(--radius);overflow:hidden;min-height:340px;background:var(--card);border:1px solid var(--line);cursor:pointer}
.hero-main .img{position:absolute;inset:0;background-size:cover;background-position:center;transition:.4s}.hero-main:hover .img{transform:scale(1.05)}
.hero-main .shade{position:absolute;inset:0;background:linear-gradient(to top,rgba(7,11,20,.96) 8%,rgba(7,11,20,.25) 60%,transparent)}
.hero-main .body{position:absolute;left:0;right:0;bottom:0;padding:26px}.hero-main h1{font-size:30px;line-height:1.2;margin:10px 0 8px;letter-spacing:-.5px}
.hero-side{display:flex;flex-direction:column;gap:16px}
.hero-s{position:relative;flex:1;border-radius:var(--radius);overflow:hidden;background:var(--card);border:1px solid var(--line);cursor:pointer;min-height:100px}
.hero-s .img{position:absolute;inset:0;background-size:cover;background-position:center}.hero-s .shade{position:absolute;inset:0;background:linear-gradient(to top,rgba(7,11,20,.95),transparent 75%)}
.hero-s .body{position:absolute;left:0;right:0;bottom:0;padding:14px}.hero-s h3{font-size:15px;line-height:1.3}
.badge{display:inline-block;font-size:11px;font-weight:800;letter-spacing:.4px;padding:3px 10px;border-radius:20px;background:var(--accent);color:#04231a}
.badge.live{background:var(--accent2);color:#fff}.badge.mine{background:var(--gold);color:#3a2900}
.src{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:7px;margin-top:6px}.src .src-name{color:var(--accent)}
.section-h{display:flex;align-items:center;gap:12px;margin:8px 0 16px}.section-h h2{font-size:20px}.section-h::after{content:"";flex:1;height:1px;background:var(--line)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;display:flex;flex-direction:column;cursor:pointer;transition:.2s}
.card:hover{transform:translateY(-4px);border-color:#3a4d72;box-shadow:0 12px 30px rgba(0,0,0,.4)}
.card .thumb{height:172px;background-size:cover;background-position:center;position:relative;background-color:#16223c}
.card .thumb.no-img{background:linear-gradient(135deg,#16223c,#0f1830)}.card .thumb .tag{position:absolute;top:10px;left:10px}
.card .c-body{padding:15px 16px 18px;display:flex;flex-direction:column;gap:9px;flex:1}.card h3{font-size:16px;line-height:1.35}
.card p{font-size:13px;color:var(--muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card .foot{margin-top:auto;display:flex;justify-content:space-between;align-items:center;font-size:11.5px;color:var(--muted)}
.empty{text-align:center;padding:70px 20px;color:var(--muted)}
.loader{display:flex;flex-direction:column;align-items:center;gap:18px;padding:70px}
.spin{width:46px;height:46px;border:4px solid var(--line);border-top-color:var(--accent);border-radius:50%;animation:spin 1s linear infinite}
.modal{position:fixed;inset:0;background:rgba(4,7,13,.8);backdrop-filter:blur(4px);z-index:100;display:none;align-items:center;justify-content:center;padding:20px}
.modal.open{display:flex}
.modal-box{background:var(--card2);border:1px solid var(--line);border-radius:var(--radius);max-width:680px;width:100%;max-height:88vh;overflow:auto;position:relative}
.modal-box .mimg{width:100%;max-height:440px;object-fit:cover;display:block;background:#0d1525}.modal-box .mbody{padding:26px}
.modal-box h2{font-size:26px;margin:12px 0;line-height:1.25}.modal-box .mtext{color:#c5d3ec;font-size:15.5px;line-height:1.7;white-space:pre-wrap}
.modal-box .mlink{display:inline-block;margin-top:20px;background:var(--accent);color:#04231a;padding:11px 20px;border-radius:10px;font-weight:700}
.mactions{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:18px}
.sharebtn{display:inline-flex;align-items:center;gap:7px;background:var(--card);border:1px solid var(--line);color:var(--txt);padding:10px 16px;border-radius:10px;font-weight:600;font-size:14px;cursor:pointer}
.sharebtn:hover{border-color:var(--accent);color:var(--accent)}
.comments{margin-top:28px;border-top:1px solid var(--line);padding-top:20px}
.comments h3{font-size:17px;margin-bottom:14px}
.cm{background:#0d1525;border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:10px}
.cm .cmhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px}
.cm b{color:var(--accent);font-size:13.5px}.cm small{color:var(--muted);font-size:11.5px}
.cm p{color:#c5d3ec;font-size:14px;line-height:1.55;white-space:pre-wrap;margin:0}
.cmEmpty{color:var(--muted);font-size:13.5px;margin-bottom:14px}
.cmForm{margin-top:14px;display:flex;flex-direction:column;gap:8px}
.cmForm input,.cmForm textarea{background:#0d1525;border:1px solid var(--line);color:var(--txt);padding:11px 13px;border-radius:9px;font-size:14px;outline:none;font-family:inherit}
.cmForm input:focus,.cmForm textarea:focus{border-color:var(--accent)}.cmForm textarea{resize:vertical;min-height:70px}
.cmForm button{align-self:flex-start;background:var(--accent);color:#04231a;border:none;padding:10px 20px;border-radius:9px;font-weight:700;font-size:14px;cursor:pointer}
.iz-toast{position:fixed;bottom:26px;left:50%;transform:translateX(-50%);background:#141d30;border:1px solid var(--accent);color:var(--accent);padding:11px 20px;border-radius:10px;font-size:14px;z-index:200;max-width:88%;word-break:break-all;text-align:center}
.contactWrap{max-width:560px}
.ctf{width:100%;background:#0d1525;border:1px solid var(--line);color:var(--txt);padding:12px 14px;border-radius:10px;font-size:14px;outline:none;font-family:inherit;margin-bottom:12px}
.ctf:focus{border-color:var(--accent)}textarea.ctf{resize:vertical;min-height:120px}
.ctbtn{background:var(--accent);color:#04231a;border:none;padding:13px 26px;border-radius:10px;font-weight:800;font-size:15px;cursor:pointer;margin-top:4px}
.modal-close{position:absolute;top:18px;right:22px;font-size:30px;color:#fff;cursor:pointer;z-index:101;background:rgba(0,0,0,.5);width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center}
label{display:block;font-size:13px;color:var(--muted);margin:14px 0 6px;font-weight:600}
input.f,textarea.f,select.f{width:100%;background:#0d1525;border:1px solid var(--line);color:var(--txt);padding:12px 14px;border-radius:10px;font-size:14px;outline:none;font-family:inherit}
input.f:focus,textarea.f:focus,select.f:focus{border-color:var(--accent)}textarea.f{resize:vertical;min-height:90px}
.btn{background:var(--accent);color:#04231a;border:none;padding:13px 22px;border-radius:10px;font-weight:800;font-size:15px;cursor:pointer;width:100%;margin-top:20px}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.mylist .li{display:flex;justify-content:space-between;align-items:center;gap:12px;background:#0d1525;border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-top:10px}
.del{background:var(--accent2);color:#fff;border:none;padding:7px 12px;border-radius:8px;cursor:pointer;font-weight:700;font-size:12px;white-space:nowrap}
footer{border-top:1px solid var(--line);text-align:center;padding:26px;color:var(--muted);font-size:13px}
@media(max-width:760px){.hero{grid-template-columns:1fr}.hero-main h1{font-size:23px}.logo{font-size:21px}.search{max-width:none}.row2{grid-template-columns:1fr}}
</style></head><body>
<header><div class="bar">
  <div class="logo" onclick="selectCat('Hamısı')"><span class="ball"></span><span class="z">İdman</span><span class="dot">24</span></div>
  <div class="search"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#8da2c5" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>
    <input id="q" type="text" placeholder="Xəbər axtar..." oninput="onSearch()"></div>
  <button class="admin-link" onclick="openAdmin()">+ Xəbər əlavə et</button>
</div></header>
<div class="ticker"><div class="wrap" id="ticker"></div></div>
<nav><div class="tabs" id="tabs"></div></nav>
<main>
  <div class="meta"><span id="status">Yüklənir...</span><button class="refresh" onclick="hardRefresh()">⟳ Yenilə</button></div>
  <div id="hero"></div>
  <div id="content"><div class="loader"><div class="spin"></div><div style="color:var(--muted)">Canlı xəbərlər gətirilir...</div></div></div>
</main>
<footer>İdman24 — Azərbaycan dilində canlı idman xəbərləri<br>Mənbələr: APA Sport, İdman Xəbər, Report · Xəbərlər birbaşa mənbə saytlardan gətirilir.</footer>
<div class="modal" id="modal" onclick="if(event.target===this)closeModal()"><div class="modal-box" id="modalBox"></div></div>
<div class="modal" id="adminModal" onclick="if(event.target===this)closeAdmin()"><div class="modal-box"><div id="adminInner"></div></div></div>
<script>
let CURRENT="Hamısı",SEARCH="",ALL=[],CATS=["Hamısı"],UPDATED=null,PW="";
const esc=s=>(s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function fmtTime(iso){if(!iso)return"";const d=new Date(iso),diff=(Date.now()-d)/1000;if(isNaN(diff))return"";
 if(diff<60)return"indicə";if(diff<3600)return Math.floor(diff/60)+" dəq əvvəl";if(diff<86400)return Math.floor(diff/3600)+" saat əvvəl";
 if(diff<604800)return Math.floor(diff/86400)+" gün əvvəl";return d.toLocaleDateString("az-AZ",{day:"numeric",month:"long"});}
async function load(){
  try{const d=await (await fetch("/api/news")).json();ALL=d.items||[];CATS=d.categories||CATS;UPDATED=d.updated;}
  catch(e){document.getElementById("status").textContent="Server ilə əlaqə yoxdur.";return;}
  document.getElementById("status").textContent=`${ALL.length} xəbər · yeniləndi ${fmtTime(UPDATED)}`;
  buildTabs();render();buildTicker();
}
async function hardRefresh(){document.getElementById("status").textContent="Yenilənir...";await fetch("/api/refresh",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});load();}
function buildTabs(){document.getElementById("tabs").innerHTML=[...CATS,"Əlaqə"].map(c=>`<button class="tab ${c===CURRENT?'active':''}" onclick="selectCat('${c}')">${c}</button>`).join("");}
function current(){let i=[...ALL];
  if(CURRENT!=="Hamısı")i=i.filter(x=>x.category===CURRENT);
  if(SEARCH){const q=SEARCH.toLowerCase();i=i.filter(x=>(x.title+" "+x.summary).toLowerCase().includes(q));}return i;}
function badge(i){return i.manual?`<span class="badge mine">★ REDAKSİYA</span>`:`<span class="badge live">${esc(i.category)}</span>`;}
function srcLine(i){return `<span class="src-name">${esc(i.source)}</span> · ${fmtTime(i.date)}`;}
function buildTicker(){const tk=document.querySelector('.ticker');if(SEARCH||CURRENT!=="Hamısı"){tk.style.display='none';return;}
  tk.style.display='block';const t=ALL.slice(0,10).map(i=>`<span>${esc(i.title)}</span>`).join("");document.getElementById("ticker").innerHTML="<b>SON DƏQİQƏ</b>"+t+t;}
function render(){if(CURRENT==="Əlaqə"){document.getElementById("hero").innerHTML="";renderContact();return;}
  const items=current(),hero=document.getElementById("hero"),content=document.getElementById("content");
  if(!items.length){hero.innerHTML="";content.innerHTML=`<div class="empty">Bu kateqoriyada xəbər tapılmadı.</div>`;return;}
  let rest=items;
  if(CURRENT==="Hamısı"&&!SEARCH&&items.length>=4){const[a,b,c]=items;
    hero.innerHTML=`<div class="hero"><div class="hero-main" onclick='openModal("${a.id}")'>
      <div class="img" ${a.image?`style="background-image:url('${esc(a.image)}')"`:'style="background:linear-gradient(135deg,#16223c,#0f1830)"'}></div><div class="shade"></div>
      <div class="body">${badge(a)}<h1>${esc(a.title)}</h1><div class="src">${srcLine(a)}</div></div></div>
      <div class="hero-side">${[b,c].map(x=>`<div class="hero-s" onclick='openModal("${x.id}")'>
        <div class="img" ${x.image?`style="background-image:url('${esc(x.image)}')"`:'style="background:linear-gradient(135deg,#16223c,#0f1830)"'}></div><div class="shade"></div>
        <div class="body">${badge(x)}<h3>${esc(x.title)}</h3><div class="src">${srcLine(x)}</div></div></div>`).join("")}</div></div>`;
    rest=items.slice(3);}else hero.innerHTML="";
  const secTitle=CURRENT==="Hamısı"?"Son Xəbərlər":(CURRENT==="Arxiv"?"Arxiv — 1 aydan köhnə xəbərlər":CURRENT);
  content.innerHTML=`<div class="section-h"><h2>${secTitle}</h2></div>
    <div class="grid">${rest.map(i=>`<div class="card" onclick='openModal("${i.id}")'>
      <div class="thumb ${i.image?'':'no-img'}" ${i.image?`style="background-image:url('${esc(i.image)}')"`:''}><span class="tag">${badge(i)}</span></div>
      <div class="c-body"><h3>${esc(i.title)}</h3>${i.summary?`<p>${esc(i.summary)}</p>`:""}
        <div class="foot"><span style="color:var(--accent)">${esc(i.source)}</span><span>${fmtTime(i.date)}</span></div></div></div>`).join("")}</div>`;}
function find(id){return ALL.find(i=>i.id===id);}
let CUR=null,EDIT_ID=null;
function renderModal(a,loading){const text=a.body||a.summary||"";
  document.getElementById("modalBox").innerHTML=`<span class="modal-close" onclick="closeModal()">×</span>
    ${a.image?`<img class="mimg" src="${esc(a.image)}" alt="">`:''}
    <div class="mbody">${badge(a)}<h2>${esc(a.title)}</h2><div class="src" style="margin-bottom:14px">${srcLine(a)} · ${esc(a.author||"")}</div>
    ${loading?`<div class="loader" style="padding:30px"><div class="spin"></div><div style="color:var(--muted);font-size:13px">Tam xəbər yüklənir...</div></div>`
      :`<div class="mtext">${esc(text||"Bu xəbərin tam mətni mənbədə mövcuddur.")}</div>
        <div class="mactions">
          ${a.link?`<a class="mlink" href="${esc(a.link)}" target="_blank" rel="noopener">Orijinal mənbə →</a>`:''}
          <button class="sharebtn" onclick="shareArticle()">↗ Paylaş</button>
          <button class="sharebtn" id="trBtn" onclick="translateArticle()">🌐 Tərcümə</button>
        </div>
        <div class="comments"><h3>Şərhlər</h3>
          <div id="cmList"><p class="cmEmpty">Yüklənir...</p></div>
          <div class="cmForm">
            <input id="cmName" placeholder="Adınız (istəyə bağlı)" maxlength="40">
            <textarea id="cmText" placeholder="Şərhinizi yazın..." maxlength="1000"></textarea>
            <button onclick="postComment()">Göndər</button>
          </div>
        </div>`}
    </div>`;}
async function openModal(id){const a=find(id);if(!a)return;CUR=a;a._tshown=false;trackArticle(a,"view");const need=!a.manual&&a.link&&(!a.body||!a.image);
  renderModal(a,need);document.getElementById("modal").classList.add("open");
  if(need){try{const e=await (await fetch("/api/article?url="+encodeURIComponent(a.link))).json();
    if(e.image&&!a.image)a.image=e.image;if(e.body)a.body=e.body;}catch(_){}
    if(document.getElementById("modal").classList.contains("open"))renderModal(a,false);render();}
  if(document.getElementById("modal").classList.contains("open"))loadComments(a.id);}
function closeModal(){document.getElementById("modal").classList.remove("open");}
function izToast(m){const t=document.createElement("div");t.className="iz-toast";t.textContent=m;document.body.appendChild(t);setTimeout(()=>t.remove(),2200);}
function trackArticle(a,type){if(!a)return;try{fetch("/api/track",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.id,type,title:a.title})});}catch(e){}}
function articleLink(a){return location.origin+location.pathname+"#a="+encodeURIComponent(a.id);}
function shareArticle(){const a=CUR;if(!a)return;trackArticle(a,"share");const url=articleLink(a);const title=a.title||"İdman24";
  if(navigator.share){navigator.share({title,url}).catch(()=>{});}
  else if(navigator.clipboard){navigator.clipboard.writeText(url).then(()=>izToast("Keçid kopyalandı: "+url)).catch(()=>izToast(url));}
  else izToast(url);}
function openFromHash(){const m=(location.hash||"").match(/[#&]a=([^&]+)/);if(m){const id=decodeURIComponent(m[1]);if(find(id))openModal(id);}}
let TR_LANG=((navigator.language||"en").split("-")[0]||"en").toLowerCase();if(TR_LANG==="az")TR_LANG="en";
async function translateArticle(){const a=CUR;if(!a)return;const btn=document.getElementById("trBtn");
  if(a._tshown){renderModal(a,false);a._tshown=false;loadComments(a.id);return;}
  if(btn)btn.textContent="Tərcümə olunur...";
  if(!a._t){try{
    const tt=await (await fetch("/api/translate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:a.title||"",tl:TR_LANG})})).json();
    const bb=await (await fetch("/api/translate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:(a.body||a.summary||""),tl:TR_LANG})})).json();
    a._t={title:tt.text||a.title,body:bb.text||(a.body||a.summary||"")};
  }catch(e){izToast("Tərcümə alınmadı");if(btn)btn.textContent="🌐 Tərcümə";return;}}
  const h=document.querySelector("#modalBox h2");if(h)h.textContent=a._t.title;
  const mt=document.querySelector("#modalBox .mtext");if(mt)mt.textContent=a._t.body;
  a._tshown=true;if(btn)btn.textContent="Orijinal dilə qayıt";}
async function loadComments(id){const box=document.getElementById("cmList");if(!box)return;
  try{const d=await (await fetch("/api/comments?id="+encodeURIComponent(id))).json();const list=d.comments||[];
    box.innerHTML=list.length?list.map(c=>`<div class="cm"><div class="cmhead"><b>${esc(c.name)}</b><small>${fmtTime(c.date)}</small></div><p>${esc(c.text)}</p></div>`).join("")
      :`<p class="cmEmpty">Hələ şərh yoxdur. İlk şərhi siz yazın.</p>`;
  }catch(e){box.innerHTML=`<p class="cmEmpty">Şərhlər yüklənmədi.</p>`;}}
async function postComment(){const a=CUR;if(!a)return;const text=document.getElementById("cmText").value.trim();
  if(!text){izToast("Şərh boş ola bilməz");return;}
  const name=(document.getElementById("cmName").value||"").trim();
  await fetch("/api/comments",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:a.id,name,text})});
  document.getElementById("cmText").value="";loadComments(a.id);izToast("Şərhiniz əlavə olundu ✓");}
/* ----- Əlaqə (contact) ----- */
function renderContact(){document.getElementById("content").innerHTML=`
  <div class="contactWrap">
    <div class="section-h"><h2>Bizimlə əlaqə</h2></div>
    <p style="color:var(--muted);margin-bottom:18px">Sual, təklif, məlumat və ya xəbər göndərmək üçün formu doldurun. Cavab almaq üçün əlaqə nömrənizi qeyd edin.</p>
    <div id="ctMsg" style="display:none;margin-bottom:12px;padding:11px 14px;border-radius:9px;font-size:14px"></div>
    <input class="ctf" id="ctName" placeholder="Adınız (istəyə bağlı)" maxlength="80">
    <input class="ctf" id="ctPhone" placeholder="Əlaqə nömrəniz" maxlength="40">
    <textarea class="ctf" id="ctText" placeholder="Mesajınız..." maxlength="3000"></textarea>
    <label style="display:block;color:var(--muted);font-size:13px;margin:2px 0 6px">Şəkil əlavə et (istəyə bağlı)</label>
    <input class="ctf" id="ctImg" type="file" accept="image/*">
    <button class="ctbtn" onclick="sendContact()">Göndər</button>
  </div>`;}
function ctMsg(t,ok){const m=document.getElementById("ctMsg");if(!m)return;m.style.display="block";m.textContent=t;
  m.style.background=ok?"rgba(0,230,168,.15)":"rgba(255,61,113,.15)";m.style.color=ok?"var(--accent)":"var(--accent2)";}
async function sendContact(){const phone=document.getElementById("ctPhone").value.trim();const text=document.getElementById("ctText").value.trim();
  if(!phone&&!text){ctMsg("Zəhmət olmasa mesaj və ya nömrə yazın.",false);return;}
  const fileEl=document.getElementById("ctImg");let image_data="";
  if(fileEl.files&&fileEl.files[0]){if(fileEl.files[0].size>5*1024*1024){ctMsg("Şəkil 5MB-dan kiçik olmalıdır.",false);return;}
    ctMsg("Göndərilir...",true);
    image_data=await new Promise(r=>{const fr=new FileReader();fr.onload=()=>r(fr.result);fr.readAsDataURL(fileEl.files[0]);});}
  const name=document.getElementById("ctName").value.trim();
  try{const r=await (await fetch("/api/contact",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,phone,message:text,image_data})})).json();
    if(r.ok){ctMsg("✓ Mesajınız göndərildi. Təşəkkürlər!",true);["ctName","ctPhone","ctText","ctImg"].forEach(i=>document.getElementById(i).value="");}
    else ctMsg(r.error||"Xəta baş verdi.",false);}catch(e){ctMsg("Xəta baş verdi.",false);}}
async function loadContacts(){const box=document.getElementById("ctInbox");if(!box)return;
  try{const d=await (await fetch("/api/contacts",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:PW})})).json();
    if(!d.ok){box.innerHTML="Yüklənmədi.";return;}const list=d.items||[];
    box.innerHTML=list.length?list.map(m=>`<div style="background:#0d1525;border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;align-items:center"><b style="color:var(--accent)">${esc(m.name||"Anonim")}</b><small style="color:var(--muted)">${fmtTime(m.date)}</small></div>
      ${m.phone?`<div style="color:var(--gold);font-size:13px;margin:3px 0">📞 ${esc(m.phone)}</div>`:""}
      ${m.message?`<p style="color:#c5d3ec;font-size:14px;margin:6px 0;white-space:pre-wrap">${esc(m.message)}</p>`:""}
      ${m.image?`<a href="${esc(m.image)}" target="_blank" rel="noopener"><img src="${esc(m.image)}" style="max-width:200px;border-radius:8px;margin-top:6px"></a>`:""}
    </div>`).join(""):`<p style="color:var(--muted)">Hələ mesaj yoxdur.</p>`;
  }catch(e){box.innerHTML="Yüklənmədi.";}}
/* ----- admin (parol qorumalı) ----- */
function openAdmin(){document.getElementById("adminModal").classList.add("open");PW?adminForm():adminLogin();}
function closeAdmin(){document.getElementById("adminModal").classList.remove("open");}
function adminLogin(){document.getElementById("adminInner").innerHTML=`<span class="modal-close" onclick="closeAdmin()">×</span>
  <div class="mbody"><h2 style="margin-top:0">Admin Girişi</h2>
  <p style="color:var(--muted);font-size:14px">Xəbər əlavə etmək üçün parol daxil edin.</p>
  <input class="f" id="pw" type="password" placeholder="Parol" onkeydown="if(event.key==='Enter')doLogin()">
  <p id="pwErr" style="color:var(--accent2);font-size:13px;display:none;margin-top:8px">Parol yanlışdır.</p>
  <button class="btn" onclick="doLogin()">Daxil ol</button></div>`;
  setTimeout(()=>document.getElementById("pw").focus(),50);}
async function doLogin(){const p=document.getElementById("pw").value;
  const r=await (await fetch("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:p})})).json();
  if(r.ok){PW=p;adminForm();}else document.getElementById("pwErr").style.display="block";}
function adminForm(){EDIT_ID=null;const opts=CATS.filter(c=>c!=="Hamısı").map(c=>`<option>${c}</option>`).join("");
  document.getElementById("adminInner").innerHTML=`<span class="modal-close" onclick="closeAdmin()">×</span>
  <div class="mbody"><h2 style="margin-top:0">Öz Xəbərini Əlavə Et</h2>
  <p style="color:var(--muted);font-size:14px">Xəbərin qızıl <b style="color:var(--gold)">REDAKSİYA</b> nişanı ilə yuxarıda görünəcək.</p>
  <div id="amsg" style="display:none;margin-top:10px;padding:10px 14px;border-radius:8px"></div>
  <label>Başlıq *</label><input class="f" id="aTitle" placeholder="Başlıq">
  <div class="row2"><div><label>Kateqoriya</label><select class="f" id="aCat">${opts}</select></div>
    <div><label>Müəllif</label><input class="f" id="aAuthor" value="Redaksiya"></div></div>
  <label>Şəkil (kompüterdən yüklə)</label><input class="f" id="aImage" type="file" accept="image/*">
  <label>Qısa təsvir</label><textarea class="f" id="aSummary" style="min-height:60px"></textarea>
  <label>Tam mətn</label><textarea class="f" id="aBody"></textarea>
  <label>Mənbə linki (istəyə bağlı)</label><input class="f" id="aLink" placeholder="https://...">
  <button class="btn" id="aSubmit" onclick="saveArticle()">Xəbəri yayımla</button>
  <h3 style="margin:26px 0 4px;font-size:16px">Əlavə etdiyim xəbərlər</h3><div class="mylist" id="myList"></div>
  <h3 style="margin:26px 0 6px;font-size:16px">📊 Statistika <span style="color:var(--muted);font-size:12px;font-weight:400">(yalnız siz görürsünüz)</span></h3>
  <div id="statsBox" style="font-size:13px;color:var(--muted)">Yüklənir...</div>
  <h3 style="margin:26px 0 6px;font-size:16px">📩 Gələn əlaqə mesajları</h3>
  <div id="ctInbox" style="font-size:13px;color:var(--muted)">Yüklənir...</div></div>`;
  renderMyList();loadStats();loadContacts();}
async function loadStats(){const box=document.getElementById("statsBox");if(!box)return;
  try{const d=await (await fetch("/api/stats",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:PW})})).json();
    if(!d.ok){box.innerHTML="Statistika yüklənmədi.";return;}
    const list=(d.items||[]).filter(i=>i.views||i.shares).slice(0,30);
    const rows=list.map(i=>`<tr><td style="padding:7px 8px;border-bottom:1px solid var(--line)">${esc(i.title||i.id)}</td>
      <td style="text-align:center;padding:7px 8px;border-bottom:1px solid var(--line);color:var(--accent);font-weight:700">${i.views}</td>
      <td style="text-align:center;padding:7px 8px;border-bottom:1px solid var(--line);color:var(--gold);font-weight:700">${i.shares}</td></tr>`).join("");
    box.innerHTML=`<div style="display:flex;gap:12px;margin-bottom:14px">
      <div style="flex:1;background:#0d1525;border:1px solid var(--line);border-radius:10px;padding:12px"><div style="color:var(--muted);font-size:12px">Ümumi oxunma</div><div style="font-size:24px;font-weight:800;color:var(--accent)">${d.totalViews}</div></div>
      <div style="flex:1;background:#0d1525;border:1px solid var(--line);border-radius:10px;padding:12px"><div style="color:var(--muted);font-size:12px">Ümumi paylaşım</div><div style="font-size:24px;font-weight:800;color:var(--gold)">${d.totalShares}</div></div></div>
      ${rows?`<table style="width:100%;border-collapse:collapse;color:var(--txt)"><thead><tr>
        <th style="text-align:left;padding:7px 8px;color:var(--muted);font-size:12px">Xəbər</th>
        <th style="padding:7px 8px;color:var(--muted);font-size:12px">Oxunma</th>
        <th style="padding:7px 8px;color:var(--muted);font-size:12px">Paylaşım</th></tr></thead><tbody>${rows}</tbody></table>`
       :`<p style="color:var(--muted)">Hələ oxunma/paylaşım qeydə alınmayıb.</p>`}`;
  }catch(e){box.innerHTML="Statistika yüklənmədi.";}}
function editArticle(id){const a=ALL.find(x=>x.id===id);if(!a)return;EDIT_ID=id;
  document.getElementById("aTitle").value=a.title||"";
  document.getElementById("aCat").value=a.category||"Digər";
  document.getElementById("aAuthor").value=a.author||"Redaksiya";
  document.getElementById("aSummary").value=a.summary||"";
  document.getElementById("aBody").value=a.body||"";
  document.getElementById("aLink").value=a.link||"";
  const sb=document.getElementById("aSubmit");if(sb)sb.textContent="Dəyişikliyi yadda saxla";
  document.getElementById("adminInner").scrollTop=0;
  amsg("Düzəliş rejimi — dəyişib yadda saxlayın (yeni şəkil seçməsəniz köhnəsi qalır)",true);}
function amsg(t,ok){const m=document.getElementById("amsg");m.style.display="block";m.textContent=t;
  m.style.background=ok?"rgba(0,230,168,.15)":"rgba(255,61,113,.15)";m.style.color=ok?"var(--accent)":"var(--accent2)";
  setTimeout(()=>{m.style.display="none";},4000);}
async function saveArticle(){const t=document.getElementById("aTitle").value.trim();if(!t){amsg("Başlıq tələb olunur.",false);return;}
  const fileEl=document.getElementById("aImage");let image_data="";
  if(fileEl.files&&fileEl.files[0]){
    if(fileEl.files[0].size>5*1024*1024){amsg("Şəkil 5MB-dan kiçik olmalıdır.",false);return;}
    amsg("Şəkil yüklənir...",true);
    image_data=await new Promise(res=>{const r=new FileReader();r.onload=()=>res(r.result);r.readAsDataURL(fileEl.files[0]);});
  }
  const payload={password:PW,id:EDIT_ID,title:t,category:document.getElementById("aCat").value,author:document.getElementById("aAuthor").value.trim(),
    image_data,summary:document.getElementById("aSummary").value.trim(),
    body:document.getElementById("aBody").value.trim(),link:document.getElementById("aLink").value.trim()};
  const ep=EDIT_ID?"/api/article/edit":"/api/article/add";
  const r=await (await fetch(ep,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)})).json();
  if(r.ok){amsg(EDIT_ID?"✓ Dəyişiklik yadda saxlanıldı!":"✓ Xəbər yayımlandı!",true);
    EDIT_ID=null;const sb=document.getElementById("aSubmit");if(sb)sb.textContent="Xəbəri yayımla";
    ["aTitle","aImage","aSummary","aBody","aLink"].forEach(i=>document.getElementById(i).value="");await load();renderMyList();}
  else amsg(r.error||"Xəta.",false);}
function renderMyList(){const mine=ALL.filter(i=>i.manual);
  document.getElementById("myList").innerHTML=mine.length?mine.map(i=>`<div class="li"><div><b>${esc(i.title)}</b><br>
    <small style="color:var(--muted)">${esc(i.category)} · ${fmtTime(i.date)}</small></div>
    <div style="display:flex;gap:8px">
      <button onclick="editArticle('${i.id}')" style="background:var(--card);border:1px solid var(--line);color:var(--txt);padding:7px 12px;border-radius:8px;cursor:pointer;font-weight:700;font-size:12px">Düzəliş</button>
      <button class="del" onclick="delArticle('${i.id}')">Sil</button></div></div>`).join(""):`<p style="color:var(--muted);font-size:13px;margin-top:8px">Hələ xəbər yoxdur.</p>`;}
async function delArticle(id){if(!confirm("Silinsin?"))return;
  await fetch("/api/article/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:PW,id})});await load();renderMyList();}
function selectCat(c){CURRENT=c;SEARCH="";document.getElementById("q").value="";window.scrollTo({top:0,behavior:"smooth"});buildTabs();render();buildTicker();}
let st;function onSearch(){SEARCH=document.getElementById("q").value;clearTimeout(st);st=setTimeout(()=>{render();buildTicker();},250);}
document.addEventListener("keydown",e=>{if(e.key==="Escape"){closeModal();closeAdmin();}});
load().then(openFromHash);window.addEventListener("hashchange",openFromHash);setInterval(load,60000);
</script></body></html>"""


if __name__ == "__main__":
    main()
