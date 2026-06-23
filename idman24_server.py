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
GEO_FILE = os.path.join(DATA_DIR, "idman24_geo.json")
DAILY_FILE = os.path.join(DATA_DIR, "idman24_daily.json")
AD_FILE = os.path.join(DATA_DIR, "idman24_ad.json")
POLL_FILE = os.path.join(DATA_DIR, "idman24_poll.json")
# Şərhlərdə qadağan sözlər (hostinqdə IDMAN24_BANNED=söz1,söz2 ilə təyin edin)
BANNED_WORDS = [w.strip() for w in os.environ.get("IDMAN24_BANNED", "").lower().split(",") if w.strip()]
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

# ---- Coğrafiya (oxucuların yeri) — yalnız admin görür ----
GEO = {}
_GEO_CACHE = {}

def load_geo():
    global GEO
    try:
        if os.path.exists(GEO_FILE):
            GEO = json.load(open(GEO_FILE, encoding="utf-8")) or {}
    except Exception as e:
        print("[load_geo]", e); GEO = {}

def save_geo():
    try:
        json.dump(GEO, open(GEO_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        print("[save_geo]", e)

def ip_location(ip):
    # IP-dən mümkün qədər dəqiq yer: şəhər + ölkə (təxmini, IP səviyyəsində)
    if not ip or re.match(r"^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1|fc|fd)", ip):
        return ""
    if ip in _GEO_CACHE:
        return _GEO_CACHE[ip]
    label = ""
    try:
        d = json.loads(http_get("http://ip-api.com/json/" + ip +
                                "?fields=status,country,regionName,city", timeout=6))
        if d.get("status") == "success":
            city = d.get("city") or d.get("regionName") or ""
            country = d.get("country") or ""
            label = ", ".join([p for p in [city, country] if p]) or country
    except Exception:
        label = ""
    _GEO_CACHE[ip] = label
    return label

def record_geo(ip):
    loc = ip_location(ip)
    if not loc:
        return
    with _slock:
        GEO[loc] = GEO.get(loc, 0) + 1
        save_geo()

# ---- Günlük oxunma trendi + mənbə statusu ----
DAILY = {}
SOURCE_STATUS = {}

def load_daily():
    global DAILY
    try:
        if os.path.exists(DAILY_FILE):
            DAILY = json.load(open(DAILY_FILE, encoding="utf-8")) or {}
    except Exception as e:
        print("[load_daily]", e); DAILY = {}

def save_daily():
    try:
        json.dump(DAILY, open(DAILY_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        print("[save_daily]", e)

def bump_daily():
    d = datetime.now(timezone.utc).date().isoformat()
    with _slock:
        DAILY[d] = DAILY.get(d, 0) + 1
        if len(DAILY) > 120:
            for k in sorted(DAILY)[:-120]:
                DAILY.pop(k, None)
        save_daily()

# ---- Reklam (banner) ----
AD = {"image": "", "link": "", "active": False}

def load_ad():
    global AD
    try:
        if os.path.exists(AD_FILE):
            AD = json.load(open(AD_FILE, encoding="utf-8")) or AD
    except Exception as e:
        print("[load_ad]", e)

def save_ad():
    try:
        json.dump(AD, open(AD_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        print("[save_ad]", e)

# ---- Sorğu (poll) ----
POLL = {"question": "", "options": [], "active": False}

def load_poll():
    global POLL
    try:
        if os.path.exists(POLL_FILE):
            POLL = json.load(open(POLL_FILE, encoding="utf-8")) or POLL
    except Exception as e:
        print("[load_poll]", e)

def save_poll():
    try:
        json.dump(POLL, open(POLL_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        print("[save_poll]", e)

# ============ Cüdo canlı nəticələr (IJF JudoBase açıq API) ============
# IOC (3 hərf) -> ISO-3166 alpha-2 (bayraq şəkilləri üçün)
_IOC2ISO = {
 "AFG":"af","ALB":"al","ALG":"dz","AND":"ad","ANG":"ao","ARG":"ar","ARM":"am","ARU":"aw","AUS":"au","AUT":"at",
 "AZE":"az","BAH":"bs","BAN":"bd","BAR":"bb","BDI":"bi","BEL":"be","BEN":"bj","BER":"bm","BHU":"bt","BIH":"ba",
 "BLR":"by","BOL":"bo","BOT":"bw","BRA":"br","BRN":"bh","BRU":"bn","BUL":"bg","BUR":"bf","CAF":"cf","CAM":"kh",
 "CAN":"ca","CAY":"ky","CGO":"cg","CHA":"td","CHI":"cl","CHN":"cn","CIV":"ci","CMR":"cm","COD":"cd","COK":"ck",
 "COL":"co","COM":"km","CPV":"cv","CRC":"cr","CRO":"hr","CUB":"cu","CYP":"cy","CZE":"cz","DEN":"dk","DJI":"dj",
 "DMA":"dm","DOM":"do","ECU":"ec","EGY":"eg","ERI":"er","ESA":"sv","ESP":"es","EST":"ee","ETH":"et","FIJ":"fj",
 "FIN":"fi","FRA":"fr","FSM":"fm","GAB":"ga","GAM":"gm","GBR":"gb","GBS":"gw","GEO":"ge","GEQ":"gq","GER":"de",
 "GHA":"gh","GRE":"gr","GRN":"gd","GUA":"gt","GUI":"gn","GUM":"gu","GUY":"gy","HAI":"ht","HKG":"hk","HON":"hn",
 "HUN":"hu","INA":"id","IND":"in","IRI":"ir","IRL":"ie","IRQ":"iq","ISL":"is","ISR":"il","ISV":"vi","ITA":"it",
 "IVB":"vg","JAM":"jm","JOR":"jo","JPN":"jp","KAZ":"kz","KEN":"ke","KGZ":"kg","KIR":"ki","KOR":"kr","KOS":"xk",
 "KSA":"sa","KUW":"kw","LAO":"la","LAT":"lv","LBA":"ly","LBN":"lb","LBR":"lr","LCA":"lc","LES":"ls","LIE":"li",
 "LTU":"lt","LUX":"lu","MAD":"mg","MAR":"ma","MAS":"my","MAW":"mw","MDA":"md","MDV":"mv","MEX":"mx","MGL":"mn",
 "MKD":"mk","MLI":"ml","MLT":"mt","MNE":"me","MON":"mc","MOZ":"mz","MRI":"mu","MTN":"mr","MYA":"mm","NAM":"na",
 "NCA":"ni","NED":"nl","NEP":"np","NGR":"ng","NIG":"ne","NOR":"no","NRU":"nr","NZL":"nz","OMA":"om","PAK":"pk",
 "PAN":"pa","PAR":"py","PER":"pe","PHI":"ph","PLE":"ps","PLW":"pw","PNG":"pg","POL":"pl","POR":"pt","PRK":"kp",
 "PUR":"pr","QAT":"qa","ROU":"ro","RSA":"za","RUS":"ru","RWA":"rw","SAM":"ws","SEN":"sn","SEY":"sc","SGP":"sg",
 "SKN":"kn","SLE":"sl","SLO":"si","SMR":"sm","SOL":"sb","SOM":"so","SRB":"rs","SRI":"lk","SSD":"ss","STP":"st",
 "SUD":"sd","SUI":"ch","SUR":"sr","SVK":"sk","SWE":"se","SWZ":"sz","SYR":"sy","TAN":"tz","TGA":"to","THA":"th",
 "TJK":"tj","TKM":"tm","TLS":"tl","TOG":"tg","TPE":"tw","TTO":"tt","TUN":"tn","TUR":"tr","TUV":"tv","UAE":"ae",
 "UGA":"ug","UKR":"ua","URU":"uy","USA":"us","UZB":"uz","VAN":"vu","VEN":"ve","VIE":"vn","VIN":"vc","YEM":"ye",
 "ZAM":"zm","ZIM":"zw"}

def _iso2(short):
    return _IOC2ISO.get((short or "").strip().upper(), "")

IJF_BASE = "https://data.ijf.org/api/get_json"
_ijf_cache = {}   # key -> (ts, data)

def ijf_get(params, ttl):
    key = "&".join("%s=%s" % (k, v) for k, v in sorted(params.items()))
    now = time.time()
    hit = _ijf_cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    q = "&".join("params%5B" + k + "%5D=" + quote(str(v)) for k, v in params.items())
    try:
        data = json.loads(http_get(IJF_BASE + "?" + q, timeout=25))
    except Exception as e:
        print("[ijf]", e)
        return hit[1] if hit else None
    _ijf_cache[key] = (now, data)
    return data

def _ijf_age(c):
    s = ((c.get("competition_code") or "") + " " + (c.get("name") or "")).lower()
    if "cadet" in s or "_cad" in s or "u18" in s:
        return "cadets"
    if "junior" in s or "_jun" in s or "u21" in s or "u23" in s:
        return "juniors"
    return "seniors"

def judo_competitions():
    data = ijf_get({"action": "competition.get_list"}, 6 * 3600)
    if not isinstance(data, list):
        return []
    today = datetime.now().strftime("%Y/%m/%d")
    cy = datetime.now().year
    out = []
    for c in data:
        try:
            y = int(c.get("comp_year") or 0)
        except Exception:
            y = 0
        if y < cy - 2:                      # son 3 il (bitmiş yarışlar da daxil)
            continue
        df = (c.get("date_from") or "").replace("\\/", "/")
        dt = (c.get("date_to") or "").replace("\\/", "/")
        if df and df > today:               # gələcək yarışlar təqvimdə göstərilir, burada yox
            continue
        out.append({"id": c.get("id_competition"),
                    "name": c.get("name") or c.get("competition_code") or "Yarış",
                    "city": c.get("city") or "", "country": c.get("country") or "",
                    "date_from": df, "date_to": dt,
                    "live": bool(df and dt and df <= today <= dt),
                    "has_results": str(c.get("has_results")) in ("1", "true", "True")})
    out.sort(key=lambda x: x["date_from"], reverse=True)        # üçüncü: ən yeni
    out.sort(key=lambda x: not x["has_results"])                # ikinci: nəticəsi olanlar (tam şəbəkə)
    out.sort(key=lambda x: not x["live"])                       # birinci: canlı yarış varsa öndə
    return out[:60]

def judo_calendar(age):
    data = ijf_get({"action": "competition.get_list"}, 6 * 3600)
    if not isinstance(data, list):
        return []
    today = datetime.now().strftime("%Y/%m/%d")
    out = []
    for c in data:
        df = (c.get("date_from") or "").replace("\\/", "/")
        if not df or df < today:            # yalnız gələcək yarışlar
            continue
        a = _ijf_age(c)
        if age and age != "all" and a != age:
            continue
        out.append({"name": c.get("name") or c.get("competition_code") or "Yarış",
                    "city": c.get("city") or "", "country": c.get("country") or "",
                    "date_from": df, "date_to": (c.get("date_to") or "").replace("\\/", "/"),
                    "age": a})
    out.sort(key=lambda x: x["date_from"])
    return out[:40]

def judo_categories(cid):
    data = ijf_get({"action": "competition.categories_full", "id_competition": cid}, 24 * 3600)
    if not isinstance(data, dict):
        return []
    out = []
    for g in data.values():
        if not isinstance(g, dict):
            continue
        gender = g.get("gender")
        for wid, label in (g.get("categories") or {}).items():
            out.append({"id": wid, "label": label, "gender": gender})
    out.sort(key=lambda x: int(x["id"]) if str(x["id"]).isdigit() else 999)
    return out

def judo_contests(cid, wid):
    data = ijf_get({"action": "contest.find", "id_competition": cid, "id_weight": wid}, 25)
    cs = data.get("contests") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    out = []
    for c in cs or []:
        idw, idb, win = c.get("id_person_white"), c.get("id_person_blue"), c.get("id_winner")
        winner = "w" if (win and win == idw) else ("b" if (win and win == idb) else "")
        def sc(p):
            return "%s-%s" % (c.get("ippon_" + p) or 0, c.get("waza_" + p) or 0)
        # Qalibi bəlli olan görüş bitmiş sayılır (köhnə yarışlarda yanlış "canlı" işığı olmasın)
        finished = str(c.get("is_finished")) in ("1", "true", "True") or bool(winner)
        out.append({"white": c.get("person_white") or "", "cw": c.get("country_short_white") or "",
                    "cwn": c.get("country_white") or "", "fw": _iso2(c.get("country_short_white")),
                    "blue": c.get("person_blue") or "", "cb": c.get("country_short_blue") or "",
                    "cbn": c.get("country_blue") or "", "fb": _iso2(c.get("country_short_blue")),
                    "sw": sc("w"), "sb": sc("b"),
                    "shidow": c.get("penalty_w") or 0, "shidob": c.get("penalty_b") or 0,
                    "winner": winner, "finished": finished,
                    "gs": str(c.get("gs")) in ("1", "true", "True"),
                    "round": c.get("round_name") or "",
                    "fid": c.get("id_fight") or "0"})
    out.sort(key=lambda x: int(x["fid"]) if str(x["fid"]).isdigit() else 0, reverse=True)
    out.sort(key=lambda x: x["finished"])   # bitməmiş (canlı) görüşlər yuxarıda
    return out

def public_live():
    # Saytda göstərmək üçün: yalnız şəkilli xəbərlər + eyni şəkli işlədən
    # təkrar/canlı yeniləmələri birləşdir (ən yenisini saxla).
    with _lock:
        items = sorted(list(LIVE), key=lambda x: x.get("date", ""), reverse=True)
    out, seen_img = [], set()
    for it in items:
        img = (it.get("image") or "").strip()
        if not img:
            continue                      # şəkilsiz xəbər saytda görünməsin
        key = img.split("?")[0]
        if key in seen_img:
            continue                      # eyni şəkilli təkrarı at
        seen_img.add(key)
        out.append(it)
    return out

def rss_xml():
    items = (load_manual() + public_live())[:40]
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<rss version="2.0"><channel>',
             '<title>İdman24 - Canlı İdman Xəbərləri</title>',
             '<link>https://idman24.com</link>',
             '<description>Azərbaycan dilində canlı idman xəbərləri</description>',
             '<language>az</language>']
    for it in items:
        link = it.get("link") or "https://idman24.com"
        title = html.escape(it.get("title", ""))
        desc = html.escape(it.get("summary", ""))
        parts.append("<item><title>%s</title><link>%s</link><description>%s</description>"
                     "<category>%s</category><pubDate>%s</pubDate></item>"
                     % (title, html.escape(link), desc, html.escape(it.get("category", "")),
                        it.get("date", "")))
    parts.append("</channel></rss>")
    return "".join(parts)

# ---- SEO: hər məqalə üçün ayrıca səhifə + sitemap ----
def find_article(aid):
    for it in load_manual():
        if it.get("id") == aid:
            return it
    with _lock:
        for it in list(LIVE):
            if it.get("id") == aid:
                return it
    return None

def article_page(it, body, img):
    title = html.escape(it.get("title", ""))
    desc = html.escape((it.get("summary") or body or "")[:200])
    image = html.escape(img or "https://idman24.com/icon.svg")
    url = "https://idman24.com/xeber/" + html.escape(it.get("id", ""))
    cat = html.escape(it.get("category", "")); src = html.escape(it.get("source", ""))
    link = html.escape(it.get("link", ""))
    paras = "".join("<p>%s</p>" % html.escape(p) for p in (body or it.get("summary", "")).split("\n") if p.strip())
    img_tag = ('<img class="h" src="%s" alt="">' % image) if img else ""
    src_link = ('<a class="cta" href="%s" target="_blank" rel="noopener">Orijinal mənbə</a>' % link) if link else ""
    return ('<!DOCTYPE html><html lang="az"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>' + title + ' - İdman24</title>'
        '<meta name="description" content="' + desc + '">'
        '<meta property="og:type" content="article"><meta property="og:title" content="' + title + '">'
        '<meta property="og:description" content="' + desc + '"><meta property="og:image" content="' + image + '">'
        '<meta property="og:url" content="' + url + '"><meta property="og:site_name" content="İdman24">'
        '<meta name="twitter:card" content="summary_large_image"><link rel="canonical" href="' + url + '">'
        '<style>body{margin:0;background:#0a0e17;color:#eaf0fb;font-family:system-ui,Segoe UI,Arial,sans-serif;line-height:1.7}'
        'a{color:#00e6a8;text-decoration:none}header{border-bottom:1px solid #22304d;padding:14px 20px;font-weight:800;font-size:22px}'
        'header span{color:#00e6a8}.w{max-width:720px;margin:0 auto;padding:20px}img.h{width:100%;border-radius:14px;margin:14px 0}'
        'h1{font-size:28px;line-height:1.25}.m{color:#8da2c5;font-size:13px;margin-bottom:10px}.b p{color:#c5d3ec;font-size:16px}'
        '.cta{display:inline-block;margin-top:18px;background:#00e6a8;color:#04231a;padding:11px 20px;border-radius:10px;font-weight:700}</style></head>'
        '<body><header><a href="/"><span>İdman</span>24</a></header>'
        '<article class="w"><div class="m">' + cat + ' &middot; ' + src + '</div><h1>' + title + '</h1>'
        + img_tag + '<div class="b">' + paras + '</div>' + src_link +
        '<p style="margin-top:24px"><a href="/">İdman24 əsas səhifə</a></p></article></body></html>')

def sitemap_xml():
    items = (load_manual() + public_live())[:300]
    urls = ['<url><loc>https://idman24.com/</loc></url>']
    for it in items:
        urls.append("<url><loc>https://idman24.com/xeber/%s</loc></url>" % html.escape(it.get("id", "")))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(urls) + '</urlset>')

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
        items = parse_feed(http_get(f["url"]), f)
        SOURCE_STATUS[f["name"]] = {"count": len(items), "ok": True, "type": "RSS"}
        return items
    except Exception as e:
        print("[fetch]", f["name"], e)
        SOURCE_STATUS[f["name"]] = {"count": 0, "ok": False, "type": "RSS"}
        return []

def _scrape_safe(s):
    items, errs = scrape_one(s)
    for e in errs: print("[scrape]", e)
    SOURCE_STATUS[s["name"]] = {"count": len(items), "ok": (len(items) > 0), "type": "Federasiya"}
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
        # Eyni şəkli işlədən təkrarları/canlı yeniləmələri sil (ən yenisi qalır)
        seen_img, deduped = set(), []
        for it in LIVE:
            img = (it.get("image") or "").strip()
            if img:
                ikey = img.split("?")[0]
                if ikey in seen_img:
                    continue
                seen_img.add(ikey)
            deduped.append(it)
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
            items = load_manual() + public_live()
            with _slock:
                for it in items:
                    it["views"] = STATS.get(it["id"], {}).get("views", 0)
            items.sort(key=lambda x: (not x.get("pinned", False), not x.get("manual", False)))
            return self._send(200, {"updated": UPDATED, "categories": CATEGORIES, "items": items})
        if u.path == "/api/ad":
            return self._send(200, AD)
        if u.path == "/api/poll":
            return self._send(200, POLL)
        if u.path == "/api/judo/competitions":
            return self._send(200, {"items": judo_competitions()})
        if u.path == "/api/judo/categories":
            cid = parse_qs(u.query).get("comp", [""])[0]
            return self._send(200, {"items": judo_categories(cid) if cid else []})
        if u.path == "/api/judo/contests":
            qs = parse_qs(u.query)
            cid = qs.get("comp", [""])[0]; wid = qs.get("weight", [""])[0]
            return self._send(200, {"items": judo_contests(cid, wid) if (cid and wid) else []})
        if u.path == "/api/judo/calendar":
            age = parse_qs(u.query).get("age", ["all"])[0]
            return self._send(200, {"items": judo_calendar(age)})
        if u.path == "/rss.xml":
            return self._send(200, rss_xml(), "application/rss+xml; charset=utf-8")
        if u.path == "/sitemap.xml":
            return self._send(200, sitemap_xml(), "application/xml; charset=utf-8")
        if u.path == "/robots.txt":
            return self._send(200, "User-agent: *\nAllow: /\nSitemap: https://idman24.com/sitemap.xml\n",
                              "text/plain; charset=utf-8")
        if u.path.startswith("/xeber/"):
            aid = u.path.split("/xeber/", 1)[1].strip("/")
            it = find_article(aid)
            if not it:
                self.send_response(302); self.send_header("Location", "/"); self.end_headers(); return
            body, img = it.get("body", ""), it.get("image", "")
            if not it.get("manual") and it.get("link") and (not body or not img):
                e = enrich(it["link"]); body = body or e.get("body", ""); img = img or e.get("image", "")
            return self._send(200, article_page(it, body, img), "text/html; charset=utf-8")
        if u.path == "/manifest.json":
            return self._send(200, {"name": "İdman24", "short_name": "İdman24",
                "start_url": "/", "display": "standalone", "background_color": "#0a0e17",
                "theme_color": "#0a0e17",
                "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}]})
        if u.path == "/icon.svg":
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
                   '<rect width="512" height="512" rx="96" fill="#0a0e17"/>'
                   '<circle cx="256" cy="256" r="150" fill="#00e6a8"/>'
                   '<circle cx="210" cy="210" r="46" fill="#fff"/></svg>')
            return self._send(200, svg, "image/svg+xml")
        if u.path == "/sw.js":
            sw = ("const C='idman24-v1';"
                  "self.addEventListener('install',e=>{self.skipWaiting();});"
                  "self.addEventListener('activate',e=>{self.clients.claim();});"
                  "self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;"
                  "e.respondWith(fetch(e.request).then(r=>{const c=r.clone();"
                  "caches.open(C).then(ca=>ca.put(e.request,c));return r;})"
                  ".catch(()=>caches.match(e.request)));});")
            return self._send(200, sw, "application/javascript; charset=utf-8")
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
            low = text.lower()
            if any(b in low for b in BANNED_WORDS):
                return self._send(400, {"ok": False, "error": "Şərhdə qadağan olunmuş söz var"})
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
                if typ == "view":
                    bump_daily()
                    xff = self.headers.get("X-Forwarded-For", "")
                    ip = (xff.split(",")[0].strip() if xff else self.client_address[0])
                    threading.Thread(target=record_geo, args=(ip,), daemon=True).start()
            return self._send(200, {"ok": True})
        if u.path == "/api/stats":
            if body.get("password") != ADMIN_PASSWORD:
                return self._send(401, {"ok": False, "error": "Parol yanlışdır"})
            with _slock:
                items = [{"id": k, "title": v.get("title", ""),
                          "views": v.get("views", 0), "shares": v.get("shares", 0)}
                         for k, v in STATS.items()]
            items.sort(key=lambda x: x["views"], reverse=True)
            with _slock:
                geo = sorted(([{"loc": k, "count": v} for k, v in GEO.items()]),
                             key=lambda x: x["count"], reverse=True)
            return self._send(200, {"ok": True,
                "totalViews": sum(i["views"] for i in items),
                "totalShares": sum(i["shares"] for i in items),
                "items": items[:100], "geo": geo[:80]})
        if u.path == "/api/dashboard":
            if body.get("password") != ADMIN_PASSWORD:
                return self._send(401, {"ok": False, "error": "Parol yanlışdır"})
            manual = load_manual()
            with _slock:
                st = [{"id": k, "title": v.get("title", ""), "views": v.get("views", 0),
                       "shares": v.get("shares", 0)} for k, v in STATS.items()]
                geo = sorted([{"loc": k, "count": v} for k, v in GEO.items()],
                             key=lambda x: x["count"], reverse=True)
                daily = sorted(DAILY.items())[-14:]
                sources = [dict(name=k, **v) for k, v in SOURCE_STATUS.items()]
            st.sort(key=lambda x: x["views"], reverse=True)
            tmap = {s["id"]: s["title"] for s in st}
            with _clock:
                total_comments = sum(len(v) for v in COMMENTS.values())
                flat = []
                for aid, arr in COMMENTS.items():
                    for c in arr:
                        flat.append({"id": aid, "title": tmap.get(aid, ""), "name": c.get("name", ""),
                                     "text": c.get("text", ""), "date": c.get("date", "")})
            flat.sort(key=lambda x: x["date"], reverse=True)
            with _ctlock:
                contacts = list(reversed(CONTACTS))[:20]
                total_contacts = len(CONTACTS)
            return self._send(200, {"ok": True,
                "totals": {"views": sum(s["views"] for s in st), "shares": sum(s["shares"] for s in st),
                           "comments": total_comments, "messages": total_contacts,
                           "myArticles": len(manual), "liveArticles": len(LIVE), "locations": len(GEO)},
                "daily": [{"date": d, "count": c} for d, c in daily],
                "geo": geo[:80], "top": st[:100], "sources": sources,
                "recentComments": flat[:30], "recentContacts": contacts, "updated": UPDATED})
        if u.path == "/api/comment/delete":
            if body.get("password") != ADMIN_PASSWORD:
                return self._send(401, {"ok": False})
            aid, dt, tx = body.get("id"), body.get("date"), body.get("text")
            with _clock:
                arr = COMMENTS.get(aid, [])
                COMMENTS[aid] = [c for c in arr if not (c.get("date") == dt and c.get("text") == tx)]
                save_comments()
            return self._send(200, {"ok": True})
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
        if u.path == "/api/article/pin":
            if body.get("password") != ADMIN_PASSWORD:
                return self._send(401, {"ok": False})
            items = load_manual()
            for it in items:
                if it.get("id") == body.get("id"):
                    it["pinned"] = not it.get("pinned", False)
                    break
            save_manual(items)
            return self._send(200, {"ok": True})
        if u.path == "/api/ad/set":
            if body.get("password") != ADMIN_PASSWORD:
                return self._send(401, {"ok": False})
            img = self._save_image(body.get("image_data") or "") or (body.get("image") or "").strip()
            AD["image"] = img
            AD["link"] = (body.get("link") or "").strip()
            AD["active"] = bool(body.get("active"))
            save_ad()
            return self._send(200, {"ok": True})
        if u.path == "/api/poll/vote":
            try:
                i = int(body.get("i"))
            except Exception:
                return self._send(400, {"ok": False})
            with _slock:
                if POLL.get("active") and 0 <= i < len(POLL.get("options", [])):
                    POLL["options"][i]["votes"] = POLL["options"][i].get("votes", 0) + 1
                    save_poll()
            return self._send(200, {"ok": True, "poll": POLL})
        if u.path == "/api/poll/set":
            if body.get("password") != ADMIN_PASSWORD:
                return self._send(401, {"ok": False})
            opts = [{"text": (t or "").strip()[:120], "votes": 0}
                    for t in (body.get("options") or []) if (t or "").strip()][:6]
            with _slock:
                POLL["question"] = (body.get("question") or "").strip()[:200]
                POLL["options"] = opts
                POLL["active"] = bool(body.get("active")) and len(opts) >= 2
                save_poll()
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})

# ============================ START ============================
def main():
    load_cache()
    load_comments()
    load_stats()
    load_geo()
    load_daily()
    load_contacts()
    load_ad()
    load_poll()
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
<link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0a0e17">
<meta name="apple-mobile-web-app-capable" content="yes"><link rel="apple-touch-icon" href="/icon.svg">
<title>İdman24 - Canlı İdman Xəbərləri</title>
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
.adbanner{display:block;position:relative;margin:0 0 22px;border-radius:14px;overflow:hidden;border:1px solid var(--line)}
.adbanner img{width:100%;display:block;max-height:170px;object-fit:cover}
.adtag{position:absolute;top:8px;right:8px;background:rgba(0,0,0,.6);color:#fff;font-size:10px;padding:2px 8px;border-radius:6px}
.trend{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-bottom:26px}
.tcard{display:flex;align-items:center;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;cursor:pointer;transition:.2s}
.tcard:hover{border-color:var(--accent)}.tnum{font-size:22px;font-weight:800;color:var(--accent);min-width:24px}
.tt{font-size:14px;font-weight:600;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.related{margin-top:24px;border-top:1px solid var(--line);padding-top:18px}.related h3{font-size:16px;margin-bottom:12px}
.related .r{display:flex;gap:12px;padding:8px 0;cursor:pointer;border-bottom:1px solid var(--line)}
.related .r:hover .rt{color:var(--accent)}
.related .rimg{width:74px;height:54px;border-radius:8px;background-size:cover;background-position:center;background-color:#16223c;flex-shrink:0}
.related .rt{font-size:13.5px;font-weight:600;line-height:1.35}
.pollbox{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:24px}
.pollq{font-weight:700;font-size:16px;margin-bottom:14px}
.pollopt{display:block;width:100%;text-align:left;background:#0d1525;border:1px solid var(--line);color:var(--txt);padding:11px 14px;border-radius:10px;margin-bottom:8px;cursor:pointer;font-size:14px}
.pollopt:hover{border-color:var(--accent);color:var(--accent)}
.favchip{background:var(--card);border:1px solid var(--line);padding:9px 14px;border-radius:30px;cursor:pointer;font-size:14px;display:inline-flex;align-items:center;gap:6px}
.judosel{display:flex;gap:10px;flex-wrap:wrap}
.judosel select{background:var(--card);border:1px solid var(--line);color:var(--txt);padding:10px 12px;border-radius:10px;font-size:14px;max-width:100%}
.jrow{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:11px 14px 12px;margin-bottom:10px;position:relative}
.jlivebox{border-color:rgba(255,61,113,.45);box-shadow:0 0 0 1px rgba(255,61,113,.15)}
.jmeta{display:flex;gap:12px;align-items:center;font-size:11px;color:var(--muted);margin-bottom:6px;text-transform:uppercase;letter-spacing:.05em}
.jlive{color:#04231a;background:var(--accent2);font-weight:800;padding:2px 8px;border-radius:20px;animation:jblink 1.4s infinite}
@keyframes jblink{50%{opacity:.55}}
.js{display:flex;justify-content:space-between;align-items:center;padding:5px 0}
.jn{font-size:14.5px;display:flex;align-items:center;gap:8px}.jn small{color:var(--muted);font-size:11px;font-weight:600;background:#0d1525;padding:1px 6px;border-radius:5px}
.gi{width:9px;height:9px;border-radius:50%;flex:0 0 auto;display:inline-block}
.gi.w{background:#e9eef7;box-shadow:0 0 0 1px var(--line)}.gi.b{background:#3b82f6}
.jvs{text-align:center;font-size:10px;color:var(--muted);font-weight:700;letter-spacing:.1em;margin:1px 0}
.jsc{font-weight:700;font-variant-numeric:tabular-nums;color:var(--muted)}
.shi{font-style:normal;background:#caa400;color:#1a1500;border-radius:4px;padding:0 5px;font-size:11px;margin-left:4px}
.jwin .jn{color:var(--accent);font-weight:700}.jwin .jsc{color:var(--accent)}
.jwin .jn:after{content:" ✓";color:var(--accent)}
.caldate small{display:block;font-size:9px;color:var(--muted);font-weight:600}
.backbtn{background:var(--card);border:1px solid var(--line);color:var(--txt);padding:8px 16px;border-radius:9px;cursor:pointer;font-size:13.5px;font-weight:600;margin-bottom:16px}
.backbtn:hover{border-color:var(--accent);color:var(--accent)}
.totop{position:fixed;right:20px;bottom:22px;width:46px;height:46px;border-radius:50%;border:none;background:var(--accent);color:#04231a;font-size:22px;font-weight:800;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.4);opacity:0;pointer-events:none;transform:translateY(12px);transition:.25s;z-index:60}
.totop.show{opacity:1;pointer-events:auto;transform:none}
.morebtn{background:var(--card);border:1px solid var(--accent);color:var(--accent);padding:12px 28px;border-radius:30px;cursor:pointer;font-size:14.5px;font-weight:700}
.morebtn:hover{background:var(--accent);color:#04231a}
.widgets{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
@media(max-width:760px){.widgets{grid-template-columns:1fr}}
.widget{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}
.widget h3{margin:0 0 12px;font-size:15px}
.wchips{display:flex;flex-wrap:wrap;gap:8px}
.wchip{background:#0d1525;border:1px solid var(--line);color:var(--txt);padding:7px 13px;border-radius:30px;cursor:pointer;font-size:13px}
.wchip:hover{border-color:var(--accent);color:var(--accent)}
.wrow{display:flex;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line);cursor:pointer}
.wrow:last-child{border-bottom:none}
.wrow:hover .wt{color:var(--accent)}
.wn{min-width:20px;height:20px;display:flex;align-items:center;justify-content:center;background:var(--accent);color:#04231a;border-radius:6px;font-size:12px;font-weight:800;flex:0 0 auto}
.wdate{min-width:42px;text-align:center;background:#0d1525;border:1px solid var(--line);border-radius:7px;padding:4px 2px;font-size:12px;font-weight:700;color:var(--accent);flex:0 0 auto}
.wt{font-size:13px;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.cudolow{display:grid;grid-template-columns:1fr 300px;gap:18px;align-items:start;margin-top:4px}
.cudonews{min-width:0}
#judoResults{max-height:430px;overflow:auto;padding-right:4px}
#judoCal{max-height:360px;overflow-y:auto;padding-right:4px}
#judoResults::-webkit-scrollbar,#judoCal::-webkit-scrollbar{width:7px;height:7px}
#judoResults::-webkit-scrollbar-thumb,#judoCal::-webkit-scrollbar-thumb{background:var(--line);border-radius:6px}
@media(max-width:760px){.cudolow{grid-template-columns:1fr}#judoResults{max-height:none}#judoCal{max-height:300px}}
.judopanel{background:linear-gradient(160deg,#101a30,#0c1424);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:14px;padding:18px;margin-bottom:22px}
.jph{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:6px;flex-wrap:wrap}.jph h2{margin:0;font-size:18px;display:inline}
.vtoggle{display:flex;gap:4px}
.vtoggle button{background:#0d1525;border:1px solid var(--line);color:var(--muted);font-size:11.5px;padding:5px 11px;border-radius:7px;cursor:pointer}
.vtoggle button.von{background:var(--accent);color:#04231a;border-color:var(--accent);font-weight:700}
.bracket{display:flex;gap:10px;overflow-x:auto;padding-bottom:8px;align-items:stretch}
.bcol{width:166px;flex:0 0 166px;display:flex;flex-direction:column}
.flag{width:18px;height:13px;object-fit:cover;border-radius:2px;flex:0 0 auto;box-shadow:0 0 0 1px rgba(0,0,0,.3)}
.cc{color:var(--muted);font-size:9.5px;flex:0 0 auto}
.bcol h4{margin:0 0 8px;font-size:10px;text-transform:uppercase;letter-spacing:.04em;color:var(--accent);text-align:center;padding-bottom:5px;border-bottom:1px solid var(--line)}
.bextra h4{color:var(--accent2)}
.bmatches{flex:1;display:flex;flex-direction:column;justify-content:space-around;gap:9px}
.bmatch{background:#0e1830;border:1.5px solid #2c3e62;border-radius:7px;overflow:hidden;position:relative}
.bmatch.blive{border-color:var(--accent2)}
.brow{display:flex;justify-content:space-between;align-items:center;gap:6px;font-size:12px;padding:6px 8px;border-bottom:1px solid #2c3e62}
.brow:last-child{border-bottom:none}
.brow span{display:flex;align-items:center;gap:5px;min-width:0}
.bnm{overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.brow small{color:var(--muted);font-size:9.5px;flex:0 0 auto}
.brow b{color:var(--muted);font-variant-numeric:tabular-nums;font-weight:700;flex:0 0 auto}
.bwin{background:rgba(0,230,168,.10);color:var(--accent);font-weight:700}.bwin b{color:var(--accent)}
.blivebadge{position:absolute;top:-7px;right:5px;background:var(--accent2);color:#04231a;font-size:8px;font-weight:800;padding:1px 5px;border-radius:10px}
.jphs{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.agefilter{display:flex;flex-wrap:wrap;gap:8px}
.agebtn{background:#0d1525;border:1px solid var(--line);color:var(--muted);padding:7px 14px;border-radius:30px;cursor:pointer;font-size:13px}
.agebtn.on{background:var(--accent);color:#04231a;border-color:var(--accent);font-weight:700}
.calrow{display:flex;gap:14px;align-items:center;padding:10px 0;border-bottom:1px solid var(--line)}
.calrow:last-child{border-bottom:none}
.caldate{min-width:52px;text-align:center;background:#0d1525;border:1px solid var(--line);border-radius:9px;padding:6px 4px;font-weight:700;font-size:13px;color:var(--accent);font-variant-numeric:tabular-nums}
.calname{font-size:14.5px;font-weight:600}.calmeta{font-size:12.5px;color:var(--muted);margin-top:2px}
.dash{position:fixed;inset:0;background:#0a0e17;z-index:150;display:none;grid-template-columns:228px 1fr}
.dash.open{display:grid}
.dashnav{background:#0f1626;border-right:1px solid var(--line);padding:18px 12px;overflow:auto}
.dashnav .dlogo{font-weight:900;font-size:19px;margin:4px 8px 18px}.dashnav .dlogo span{color:var(--accent)}
.dashnav button{display:block;width:100%;text-align:left;background:transparent;border:none;color:var(--muted);padding:11px 13px;border-radius:9px;font-size:14px;cursor:pointer;font-weight:600;margin-bottom:3px}
.dashnav button:hover{color:var(--txt);background:#141d30}.dashnav button.on{background:var(--accent);color:#04231a}
.dashmain{padding:24px 28px;overflow:auto}.dashmain h2{font-size:22px;margin-bottom:3px}
.dashmain .sub{color:var(--muted);font-size:13px;margin-bottom:20px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:13px;margin-bottom:22px}
.kpi{background:#0f1626;border:1px solid var(--line);border-radius:12px;padding:15px}
.kpi .k{color:var(--muted);font-size:12px;margin-bottom:6px}.kpi .v{font-size:27px;font-weight:800}
.panel{background:#0f1626;border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:18px}
.panel h3{font-size:15px;margin-bottom:13px}
.bars{display:flex;align-items:flex-end;gap:6px;height:130px}
.bars .bar{background:var(--accent);border-radius:4px 4px 0 0;min-height:3px;width:100%}
.bars .bl{color:var(--muted);font-size:10px;text-align:center;margin-top:5px}
.dtable{width:100%;border-collapse:collapse;font-size:13px}
.dtable th{text-align:left;color:var(--muted);font-size:12px;padding:7px 8px;border-bottom:1px solid var(--line)}
.dtable td{padding:8px;border-bottom:1px solid var(--line)}
.dgrid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:780px){.dash.open{grid-template-columns:1fr;grid-template-rows:auto 1fr}
  .dashnav{border-right:none;border-bottom:1px solid var(--line);display:flex;gap:6px;overflow-x:auto;padding:10px}
  .dashnav .dlogo{display:none}.dashnav button{width:auto;white-space:nowrap;margin:0}.dgrid{grid-template-columns:1fr}}
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
<button id="toTop" class="totop" title="Yuxarı qalx" onclick="window.scrollTo({top:0,behavior:'smooth'})">↑</button>
<div class="modal" id="modal" onclick="if(event.target===this)closeModal()"><div class="modal-box" id="modalBox"></div></div>
<div class="modal" id="adminModal" onclick="if(event.target===this)closeAdmin()"><div class="modal-box"><div id="adminInner"></div></div></div>
<div class="dash" id="dash"><aside class="dashnav" id="dashNav"></aside><main class="dashmain" id="dashMain"></main></div>
<script>
let CURRENT="Hamısı",SEARCH="",ALL=[],CATS=["Hamısı"],UPDATED=null,PW="",AD_DATA=null,POLL_DATA=null,FAV_EDIT=false;
let FAVS=[];try{FAVS=JSON.parse(localStorage.getItem("idman24_favs")||"[]");}catch(e){FAVS=[];}
function saveFavs(){try{localStorage.setItem("idman24_favs",JSON.stringify(FAVS));}catch(e){}}
const esc=s=>(s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function fmtTime(iso){if(!iso)return"";const d=new Date(iso),diff=(Date.now()-d)/1000;if(isNaN(diff))return"";
 if(diff<60)return"indicə";if(diff<3600)return Math.floor(diff/60)+" dəq əvvəl";if(diff<86400)return Math.floor(diff/3600)+" saat əvvəl";
 if(diff<604800)return Math.floor(diff/86400)+" gün əvvəl";return d.toLocaleDateString("az-AZ",{day:"numeric",month:"long"});}
async function load(){
  try{const d=await (await fetch("/api/news")).json();ALL=d.items||[];CATS=d.categories||CATS;UPDATED=d.updated;}
  catch(e){document.getElementById("status").textContent="Server ilə əlaqə yoxdur.";return;}
  try{AD_DATA=await (await fetch("/api/ad")).json();}catch(e){AD_DATA=null;}
  try{POLL_DATA=await (await fetch("/api/poll")).json();}catch(e){POLL_DATA=null;}
  document.getElementById("status").textContent=`${ALL.length} xəbər · yeniləndi ${fmtTime(UPDATED)}`;
  buildTabs();render();buildTicker();
}
async function hardRefresh(){document.getElementById("status").textContent="Yenilənir...";await fetch("/api/refresh",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});load();}
function buildTabs(){const list=[CATS[0],"⭐ Mənim",...CATS.slice(1),"Əlaqə"];document.getElementById("tabs").innerHTML=list.map(c=>`<button class="tab ${c===CURRENT?'active':''}" onclick="selectCat('${c}')">${c}</button>`).join("");}
function current(){let i=[...ALL];
  if(CURRENT!=="Hamısı")i=i.filter(x=>x.category===CURRENT);
  if(SEARCH){const q=SEARCH.toLowerCase();i=i.filter(x=>(x.title+" "+x.summary).toLowerCase().includes(q));}return i;}
function badge(i){return i.manual?`<span class="badge mine">★ REDAKSİYA</span>`:`<span class="badge live">${esc(i.category)}</span>`;}
function srcLine(i){return `<span class="src-name">${esc(i.source)}</span> · ${fmtTime(i.date)}`;}
function buildTicker(){const tk=document.querySelector('.ticker');if(SEARCH||CURRENT!=="Hamısı"){tk.style.display='none';return;}
  tk.style.display='block';const t=ALL.slice(0,10).map(i=>`<span>${esc(i.title)}</span>`).join("");document.getElementById("ticker").innerHTML="<b>SON DƏQİQƏ</b>"+t+t;}
function render(){if(CURRENT==="Əlaqə"){document.getElementById("hero").innerHTML="";renderContact();return;}
  if(CURRENT==="⭐ Mənim"){document.getElementById("hero").innerHTML="";renderPersonal();return;}
  const items=current(),hero=document.getElementById("hero"),content=document.getElementById("content");
  if(CURRENT==="Cüdo"){renderCudo(items);return;}
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
  const secTitle=CURRENT==="Hamısı"?"Son Xəbərlər":CURRENT;
  let prefix="";
  if(CURRENT==="Hamısı"&&!SEARCH){
    if(AD_DATA&&AD_DATA.active&&AD_DATA.image){prefix+=`<a class="adbanner" href="${esc(AD_DATA.link||'#')}" target="_blank" rel="noopener"><img src="${esc(AD_DATA.image)}" alt="reklam"><span class="adtag">Reklam</span></a>`;}
    prefix+=pollHtml();
    const trend=[...ALL].filter(x=>x.views>0).sort((a,b)=>b.views-a.views).slice(0,5);
    if(trend.length>=3){prefix+=`<div class="section-h"><h2>🔥 Ən çox oxunan</h2></div><div class="trend">${trend.map((i,n)=>`<div class="tcard" onclick='openModal("${i.id}")'><span class="tnum">${n+1}</span><div><div class="tt">${esc(i.title)}</div><small style="color:var(--muted)">${esc(i.source)} · 👁 ${i.views}</small></div></div>`).join("")}</div>`;}
  }
  const shown=rest.slice(0,SHOWN);
  const moreBtn=rest.length>SHOWN?`<div style="text-align:center;margin:22px 0"><button class="morebtn" onclick="showMore()">Daha çox xəbər göstər (${rest.length-SHOWN})</button></div>`:"";
  const widgets=(CURRENT==="Hamısı"&&!SEARCH)?widgetsHtml():"";
  content.innerHTML=prefix+`<div class="section-h"><h2>${secTitle}</h2></div>
    <div class="grid">${shown.map(i=>cardHtml(i)).join("")}</div>`+moreBtn+widgets;
  if(CURRENT==="Hamısı"&&!SEARCH)loadWidgetJudo();}
function widgetsHtml(){
  const cats=CATS.filter(c=>c!=="Hamısı"&&c!=="Digər");
  const chips=cats.map(c=>`<button class="wchip" onclick="selectCat('${c}')">${esc(c)}</button>`).join("")
    +`<button class="wchip" onclick="selectCat('⭐ Mənim')">⭐ Mənim lentim</button>`;
  const top=[...ALL].filter(x=>x.views>0).sort((a,b)=>b.views-a.views).slice(0,5);
  const topHtml=top.length?top.map((i,n)=>`<div class="wrow" onclick='openModal("${i.id}")'><span class="wn">${n+1}</span><span class="wt">${esc(i.title)}</span></div>`).join(""):'<p style="color:var(--muted);font-size:13px">Hələ statistika toplanır.</p>';
  return `<div class="section-h" style="margin-top:34px"><h2>Faydalı</h2></div>
   <div class="widgets">
     <div class="widget"><h3>🏆 İdman fənləri</h3><div class="wchips">${chips}</div></div>
     <div class="widget"><h3>🥋 Yaxınlaşan cüdo yarışları</h3><div id="wJudo"><div class="loader" style="padding:14px"><div class="spin"></div></div></div></div>
     <div class="widget"><h3>🔥 Ən çox oxunan</h3>${topHtml}</div>
   </div>`;}
async function loadWidgetJudo(){const box=document.getElementById("wJudo");if(!box)return;
  let items=[];try{items=((await (await fetch("/api/judo/calendar?age=all")).json()).items)||[];}catch(e){}
  if(!box.isConnected)return;
  box.innerHTML=items.length?items.slice(0,5).map(c=>{const d=(c.date_from||"").split("/");const dd=d.length===3?`${d[2]}.${d[1]}`:"";
    return `<div class="wrow" onclick="selectCat('Cüdo')"><span class="wdate">${dd}</span><span class="wt">${esc(c.name)}</span></div>`;}).join("")
    :'<p style="color:var(--muted);font-size:13px">Yaxın yarış tapılmadı.</p>';}
function cardHtml(i){return `<div class="card" onclick='openModal("${i.id}")'>
  <div class="thumb ${i.image?'':'no-img'}" ${i.image?`style="background-image:url('${esc(i.image)}')"`:''}><span class="tag">${badge(i)}</span></div>
  <div class="c-body"><h3>${esc(i.title)}</h3>${i.summary?`<p>${esc(i.summary)}</p>`:""}
    <div class="foot"><span style="color:var(--accent)">${esc(i.source)}</span><span>${i.views?`👁 ${i.views} · `:""}${fmtTime(i.date)}</span></div></div></div>`;}
function pollHtml(){const p=POLL_DATA;if(!p||!p.active||!(p.options&&p.options.length>=2))return"";
  const total=p.options.reduce((s,o)=>s+(o.votes||0),0);
  const voted=localStorage.getItem("idman24_pollvoted")===p.question;
  let inner;
  if(voted){inner=p.options.map(o=>{const pct=total?Math.round((o.votes||0)/total*100):0;
    return `<div style="margin-bottom:9px"><div style="display:flex;justify-content:space-between;font-size:13.5px;margin-bottom:4px"><span>${esc(o.text)}</span><span style="color:var(--accent);font-weight:700">${pct}%</span></div><div style="background:#0d1525;border-radius:6px;height:10px;overflow:hidden"><div style="width:${pct}%;height:10px;background:var(--accent)"></div></div></div>`;}).join("")
    +`<div style="color:var(--muted);font-size:12px;margin-top:8px">${total} səs · təşəkkürlər</div>`;}
  else{inner=p.options.map((o,i)=>`<button class="pollopt" onclick="votePoll(${i})">${esc(o.text)}</button>`).join("");}
  return `<div class="pollbox"><div class="pollq">🗳️ ${esc(p.question)}</div>${inner}</div>`;}
async function votePoll(i){const p=POLL_DATA;if(!p)return;
  try{const r=await (await fetch("/api/poll/vote",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({i})})).json();
    if(r.poll)POLL_DATA=r.poll;}catch(e){}
  try{localStorage.setItem("idman24_pollvoted",p.question);}catch(e){}render();}
function backBtn(){return `<button class="backbtn" onclick="selectCat('Hamısı')">← Əsas səhifəyə qayıt</button>`;}
function renderPersonal(){const content=document.getElementById("content");
  if(!FAVS.length||FAV_EDIT){content.innerHTML=favPicker();return;}
  const items=ALL.filter(x=>FAVS.includes(x.category));
  content.innerHTML=backBtn()+`<div class="section-h"><h2>⭐ Mənim lentim</h2></div>
    <div style="margin-bottom:16px"><button class="refresh" onclick="editFavs()">Fənləri dəyiş</button></div>
    <div class="grid">${items.length?items.map(i=>cardHtml(i)).join(""):'<p style="color:var(--muted)">Seçdiyiniz fənlər üzrə hələ xəbər yoxdur.</p>'}</div>`;}
function favPicker(){const cats=CATS.filter(c=>c!=="Hamısı");
  return backBtn()+`<div class="section-h"><h2>⭐ Mənim lentim</h2></div>
   <p style="color:var(--muted);margin-bottom:16px;max-width:560px">Maraqlandığınız idman fənlərini seçin — əsas səhifədə yalnız onların xəbərlərini görəcəksiniz. Seçim bu brauzerdə yadda saxlanılır.</p>
   <div style="display:flex;flex-wrap:wrap;gap:9px;margin-bottom:20px">${cats.map(c=>`<label class="favchip"><input type="checkbox" value="${esc(c)}" ${FAVS.includes(c)?'checked':''}>${esc(c)}</label>`).join("")}</div>
   <button class="refresh" onclick="saveFavsFromPicker()">Yadda saxla</button>`;}
function saveFavsFromPicker(){FAVS=[...document.querySelectorAll('#content input[type=checkbox]:checked')].map(c=>c.value);FAV_EDIT=false;saveFavs();render();}
function editFavs(){FAV_EDIT=true;render();}
let JUDO={comps:null,cats:[],cid:"",wid:"",t:null,view:"bracket",items:[]};
let JCAL={age:"all"};
function judoPanelHtml(){return `<div class="judopanel">
   <div class="jph"><div><h2>🥋 Canlı nəticələr</h2> <span class="jphs">IJF JudoBase</span></div>
     <div class="vtoggle"><button id="vBr" class="${JUDO.view!=='list'?'von':''}" onclick="judoSetView('bracket')">Cədvəl</button><button id="vLi" class="${JUDO.view==='list'?'von':''}" onclick="judoSetView('list')">Siyahı</button></div></div>
   <p style="color:var(--muted);margin:8px 0 12px;font-size:13.5px">Yarışı və çəki dərəcəsini seçin — finala qədər şəbəkə (draw) görünür, canlı görüşlər hər 10 dəqiqədən bir yenilənir.</p>
   <div class="judosel">
     <select id="judoComp" onchange="judoPickComp()"><option>Yüklənir...</option></select>
     <select id="judoWeight" onchange="judoPickWeight()"><option>—</option></select>
   </div>
   <div id="judoResults" style="margin-top:16px"><div class="loader" style="padding:24px"><div class="spin"></div></div></div></div>`;}
function judoCalHtml(){return `<div class="judopanel calpanel">
   <div class="jph"><h2>📅 Gələcək yarışlar</h2><span class="jphs">Təqvim</span></div>
   <div class="agefilter">
     <button class="agebtn on" data-age="all" onclick="judoCalPick('all')">Hamısı</button>
     <button class="agebtn" data-age="cadets" onclick="judoCalPick('cadets')">Kadetlər</button>
     <button class="agebtn" data-age="juniors" onclick="judoCalPick('juniors')">Gənclər</button>
     <button class="agebtn" data-age="seniors" onclick="judoCalPick('seniors')">Böyüklər</button>
   </div>
   <div id="judoCal" style="margin-top:14px"><div class="loader" style="padding:20px"><div class="spin"></div></div></div></div>`;}
function ageLabel(a){return a==="cadets"?"Kadetlər":a==="juniors"?"Gənclər":"Böyüklər";}
function calRow(c){const d=(c.date_from||"").split("/");const dd=d.length===3?`${d[2]}.${d[1]}`:(c.date_from||"");
  const yr=d.length===3?d[0]:"";const loc=[c.city,c.country].filter(Boolean).map(esc).join(", ");
  return `<div class="calrow"><div class="caldate">${dd}<small>${yr}</small></div>
    <div class="calbody"><div class="calname">${esc(c.name)}</div><div class="calmeta">${loc}${loc?' · ':''}${ageLabel(c.age)}</div></div></div>`;}
async function judoCalLoad(){const box=document.getElementById("judoCal");if(!box)return;
  box.innerHTML='<div class="loader" style="padding:18px"><div class="spin"></div></div>';
  let items=[];try{items=((await (await fetch("/api/judo/calendar?age="+encodeURIComponent(JCAL.age))).json()).items)||[];}catch(e){}
  if(CURRENT!=="Cüdo")return;
  box.innerHTML=items.length?items.map(calRow).join(""):'<p style="color:var(--muted)">Bu kateqoriyada planlaşdırılmış yarış tapılmadı.</p>';}
function judoCalPick(a){JCAL.age=a;document.querySelectorAll('.agebtn').forEach(b=>b.classList.toggle('on',b.dataset.age===a));judoCalLoad();}
function renderCudo(items){document.getElementById("hero").innerHTML="";
  const news=items.length
    ?`<div class="section-h"><h2>Cüdo xəbərləri</h2></div><div class="grid">${items.map(cardHtml).join("")}</div>`
    :`<div class="empty" style="margin-top:18px">Hələ cüdo xəbəri yoxdur.</div>`;
  document.getElementById("content").innerHTML=backBtn()+judoPanelHtml()+`<div class="cudolow"><div class="cudonews">${news}</div>${judoCalHtml()}</div>`;
  judoInit();judoCalLoad();}
async function judoInit(){
  if(!JUDO.comps){try{JUDO.comps=((await (await fetch("/api/judo/competitions")).json()).items)||[];}catch(e){JUDO.comps=[];}}
  const sel=document.getElementById("judoComp");if(!sel)return;
  if(!JUDO.comps.length){sel.innerHTML='<option>Məlumat yoxdur</option>';document.getElementById("judoResults").innerHTML='<p style="color:var(--muted)">Hazırda nəticə məlumatı əlçatan deyil.</p>';return;}
  sel.innerHTML=JUDO.comps.map(c=>`<option value="${c.id}">${c.live?'🔴 ':''}${esc(c.name)}${c.city?' — '+esc(c.city):''}</option>`).join("");
  // Çəki dərəcələri olan ilk yarışı default seç (canlı/yeni yarışlarda hələ çəkilər boş ola bilər)
  for(let i=0;i<Math.min(JUDO.comps.length,8);i++){
    if(CURRENT!=="Cüdo")return;
    JUDO.cid=JUDO.comps[i].id;sel.value=JUDO.cid;
    if(await judoLoadCats())return;
  }}
async function judoPickComp(){JUDO.cid=document.getElementById("judoComp").value;await judoLoadCats();}
async function judoLoadCats(){const w=document.getElementById("judoWeight");if(!w)return false;w.innerHTML='<option>...</option>';
  try{JUDO.cats=((await (await fetch("/api/judo/categories?comp="+encodeURIComponent(JUDO.cid))).json()).items)||[];}catch(e){JUDO.cats=[];}
  if(!JUDO.cats.length){w.innerHTML='<option>—</option>';document.getElementById("judoResults").innerHTML='<p style="color:var(--muted)">Bu yarış üçün çəki məlumatı yoxdur.</p>';return false;}
  w.innerHTML=JUDO.cats.map(c=>`<option value="${c.id}">${c.gender==='f'?'Qadın':'Kişi'} ${esc(c.label)} kq</option>`).join("");
  JUDO.wid=JUDO.cats[0].id;w.value=JUDO.wid;await judoLoadContests();return true;}
async function judoPickWeight(){JUDO.wid=document.getElementById("judoWeight").value;await judoLoadContests();}
async function judoLoadContests(){const box=document.getElementById("judoResults");if(!box)return;
  if(JUDO.t){clearTimeout(JUDO.t);JUDO.t=null;}
  box.innerHTML='<div class="loader" style="padding:24px"><div class="spin"></div></div>';
  let items=[];try{items=((await (await fetch(`/api/judo/contests?comp=${encodeURIComponent(JUDO.cid)}&weight=${encodeURIComponent(JUDO.wid)}`)).json()).items)||[];}catch(e){}
  if(CURRENT!=="Cüdo")return;
  JUDO.items=items;judoRenderResults();
  if(items.some(x=>!x.finished)){JUDO.t=setTimeout(()=>{if(CURRENT==="Cüdo")judoLoadContests();},600000);}}
function judoRenderResults(){const box=document.getElementById("judoResults");if(!box)return;
  const items=JUDO.items||[];
  if(!items.length){box.innerHTML='<p style="color:var(--muted)">Bu çəkidə hələ görüş yoxdur.</p>';return;}
  box.innerHTML=JUDO.view==="list"?items.map(judoRow).join(""):bracketHtml(items);}
function judoSetView(v){JUDO.view=v;const a=document.getElementById("vBr"),b=document.getElementById("vLi");
  if(a)a.classList.toggle("von",v==="bracket");if(b)b.classList.toggle("von",v==="list");judoRenderResults();}
function roundKey(n){const s=(n||"").toLowerCase().replace(/[^a-z0-9]/g,"");
  if(s.includes("repech"))return"rep";if(s.includes("bronze"))return"bronze";
  if(s.includes("64"))return"r64";if(s.includes("32"))return"r32";if(s.includes("16"))return"r16";
  if(s.includes("quarter"))return"qf";if(s.includes("semi"))return"sf";
  if(s.includes("final"))return"final";return"other";}
const RLAB={r64:"1/32 final",r32:"1/16 final",r16:"1/8 final",qf:"Çərək final",sf:"Yarımfinal",final:"Final",rep:"Repesaj",bronze:"Bürünc medal",other:"Digər"};
function shortName(n){n=(n||"").trim();if(!n)return"—";const t=n.split(/\s+/);if(t.length<2)return n;
  let sur=t.find(x=>x.length>1&&x===x.toUpperCase())||t[0];
  const given=t.filter(x=>x!==sur).join(" ").trim();
  const tc=sur.charAt(0).toUpperCase()+sur.slice(1).toLowerCase();
  return given?`${tc} ${given[0].toUpperCase()}.`:tc;}
function flagImg(iso,code,name){return iso?`<img class="flag" src="https://flagcdn.com/h20/${iso}.png" alt="${esc(code||'')}" title="${esc(name||code||'')}" loading="lazy">`:(code?`<small class="cc">${esc(code)}</small>`:"");}
function bMatch(c){const live=!c.finished;
  return `<div class="bmatch ${live?'blive':''}">
    <div class="brow ${c.winner==='w'?'bwin':''}"><span>${flagImg(c.fw,c.cw,c.cwn)}<span class="bnm" title="${esc(c.white||'')}">${esc(shortName(c.white))}</span></span><b>${esc(c.sw)}</b></div>
    <div class="brow ${c.winner==='b'?'bwin':''}"><span>${flagImg(c.fb,c.cb,c.cbn)}<span class="bnm" title="${esc(c.blue||'')}">${esc(shortName(c.blue))}</span></span><b>${esc(c.sb)}</b></div>
    ${live?'<span class="blivebadge">CANLI</span>':''}</div>`;}
function bracketHtml(items){const g={};items.forEach(c=>{const k=roundKey(c.round);(g[k]=g[k]||[]).push(c);});
  const order=["r64","r32","r16","qf","sf","final","rep","bronze","other"];
  let h='<div class="bracket">';let any=false;
  order.forEach(k=>{if(!g[k])return;any=true;const ex=(k==="rep"||k==="bronze")?"bextra":"";
    h+=`<div class="bcol ${ex}"><h4>${RLAB[k]}</h4><div class="bmatches">${g[k].map(bMatch).join("")}</div></div>`;});
  h+='</div>';
  return any?h:'<p style="color:var(--muted)">Cədvəl məlumatı yoxdur.</p>';}
function judoSide(name,iso,code,cname,score,win,shido,color){return `<div class="js ${win?'jwin':''}"><span class="jn"><i class="gi ${color}"></i>${flagImg(iso,code,cname)}${esc(name||'—')}</span><span class="jsc">${esc(score)}${shido?` <i class="shi">${shido}</i>`:''}</span></div>`;}
function judoRow(c){const live=!c.finished;
  return `<div class="jrow ${live?'jlivebox':''}"><div class="jmeta">${live?'<span class="jlive">CANLI</span>':''}${c.round?`<span>${esc(c.round)}</span>`:''}${c.gs?'<span>Qızıl Hesab</span>':''}</div>
    ${judoSide(c.white,c.fw,c.cw,c.cwn,c.sw,c.winner==='w',c.shidow,'w')}
    <div class="jvs">VS</div>
    ${judoSide(c.blue,c.fb,c.cb,c.cbn,c.sb,c.winner==='b',c.shidob,'b')}</div>`;}
function find(id){return ALL.find(i=>i.id===id);}
function relatedHtml(a){const rel=ALL.filter(x=>x.category===a.category&&x.id!==a.id).slice(0,4);
  if(!rel.length)return"";
  return `<div class="related"><h3>Oxşar xəbərlər</h3>${rel.map(r=>`<div class="r" onclick='openModal("${r.id}")'>
    <div class="rimg" ${r.image?`style="background-image:url('${esc(r.image)}')"`:''}></div><div class="rt">${esc(r.title)}</div></div>`).join("")}</div>`;}
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
        ${relatedHtml(a)}
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
function articleLink(a){return location.origin+"/xeber/"+encodeURIComponent(a.id);}
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
  try{const d=await (await fetch("/api/comments?id="+encodeURIComponent(id))).json();const list=(d.comments||[]).slice().reverse();
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
  ${backBtn()}
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
function openAdmin(){if(PW){dashOpen();}else{document.getElementById("adminModal").classList.add("open");adminLogin();}}
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
  if(r.ok){PW=p;saveAdminSession(p);dashOpen();}else document.getElementById("pwErr").style.display="block";}
function saveAdminSession(p){try{localStorage.setItem("idman24_admin",JSON.stringify({p:btoa(unescape(encodeURIComponent(p))),e:Date.now()+7*864e5}));}catch(e){}}
function restoreAdminSession(){try{const o=JSON.parse(localStorage.getItem("idman24_admin")||"null");if(o&&o.e>Date.now()){PW=decodeURIComponent(escape(atob(o.p)));}else localStorage.removeItem("idman24_admin");}catch(e){}}
function adminLogout(){PW="";try{localStorage.removeItem("idman24_admin");}catch(e){}dashClose();izToast("Çıxış edildi");}
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
    const geo=d.geo||[];
    const geoHtml=geo.length?`<h4 style="margin:20px 0 8px;font-size:14px;color:var(--txt)">🌍 Oxucuların yeri</h4>`+
      geo.map(g=>`<div style="display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px solid var(--line)"><span>${esc(g.loc)}</span><b style="color:var(--accent)">${g.count}</b></div>`).join(""):"";
    box.innerHTML=`<div style="display:flex;gap:12px;margin-bottom:14px">
      <div style="flex:1;background:#0d1525;border:1px solid var(--line);border-radius:10px;padding:12px"><div style="color:var(--muted);font-size:12px">Ümumi oxunma</div><div style="font-size:24px;font-weight:800;color:var(--accent)">${d.totalViews}</div></div>
      <div style="flex:1;background:#0d1525;border:1px solid var(--line);border-radius:10px;padding:12px"><div style="color:var(--muted);font-size:12px">Ümumi paylaşım</div><div style="font-size:24px;font-weight:800;color:var(--gold)">${d.totalShares}</div></div></div>
      ${rows?`<table style="width:100%;border-collapse:collapse;color:var(--txt)"><thead><tr>
        <th style="text-align:left;padding:7px 8px;color:var(--muted);font-size:12px">Xəbər</th>
        <th style="padding:7px 8px;color:var(--muted);font-size:12px">Oxunma</th>
        <th style="padding:7px 8px;color:var(--muted);font-size:12px">Paylaşım</th></tr></thead><tbody>${rows}</tbody></table>`
       :`<p style="color:var(--muted)">Hələ oxunma/paylaşım qeydə alınmayıb.</p>`}${geoHtml}`;
  }catch(e){box.innerHTML="Statistika yüklənmədi.";}}
function editArticle(id){const a=ALL.find(x=>x.id===id);if(!a)return;EDIT_ID=id;
  document.getElementById("aTitle").value=a.title||"";
  document.getElementById("aCat").value=a.category||"Digər";
  document.getElementById("aAuthor").value=a.author||"Redaksiya";
  document.getElementById("aSummary").value=a.summary||"";
  document.getElementById("aBody").value=a.body||"";
  document.getElementById("aLink").value=a.link||"";
  const sb=document.getElementById("aSubmit");if(sb)sb.textContent="Dəyişikliyi yadda saxla";
  const at=document.getElementById("aTitle");if(at)at.scrollIntoView({behavior:"smooth",block:"center"});
  amsg("Düzəliş rejimi — dəyişib yadda saxlayın (yeni şəkil seçməsəniz köhnəsi qalır)",true);}
/* ----- Admin Dashboard ----- */
let DASH=null,DSEC="overview";
async function dashOpen(){document.getElementById("adminModal").classList.remove("open");
  document.getElementById("dash").classList.add("open");DSEC="overview";
  document.getElementById("dashMain").innerHTML='<p style="color:var(--muted)">Yüklənir...</p>';
  await dashLoad();dashRender();}
function dashClose(){document.getElementById("dash").classList.remove("open");}
async function dashLoad(){try{DASH=await (await fetch("/api/dashboard",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:PW})})).json();}catch(e){DASH={ok:false};}}
function dashNav(s){DSEC=s;dashRender();}
function dashRender(){const nav=[["overview","📊 İcmal"],["articles","📰 Xəbərlərim"],["poll","🗳️ Sorğu"],["stats","📈 Statistika"],["comments","💬 Şərhlər"],["contacts","📩 Mesajlar"],["ad","📢 Reklam"],["sources","🌐 Mənbələr"]];
  document.getElementById("dashNav").innerHTML=`<div class="dlogo"><span>İdman</span>24 · Admin</div>`+
    nav.map(n=>`<button class="${DSEC===n[0]?'on':''}" onclick="dashNav('${n[0]}')">${n[1]}</button>`).join("")+
    `<button onclick="dashClose()" style="margin-top:18px;color:var(--accent2)">← Sayta qayıt</button>`+
    `<button onclick="adminLogout()" style="margin-top:4px;color:var(--muted)">🔒 Çıxış</button>`;
  const m=document.getElementById("dashMain");
  if(DSEC==="overview")m.innerHTML=dashOverview();
  else if(DSEC==="articles"){m.innerHTML=dashArticles();renderMyList();}
  else if(DSEC==="stats")m.innerHTML=dashStats();
  else if(DSEC==="comments")m.innerHTML=dashComments();
  else if(DSEC==="contacts")m.innerHTML=dashContacts();
  else if(DSEC==="ad")m.innerHTML=dashAd();
  else if(DSEC==="poll")m.innerHTML=dashPoll();
  else if(DSEC==="sources")m.innerHTML=dashSources();
  m.scrollTop=0;}
function dashPoll(){const p=POLL_DATA||{};const opts=(p.options||[]).map(o=>o.text).join("\n");
  const total=(p.options||[]).reduce((s,o)=>s+(o.votes||0),0);
  const results=(p.options||[]).length?`<div class="panel" style="max-width:620px;margin-top:14px"><h3 style="margin:0 0 10px">Cari nəticələr (${total} səs)</h3>`+
    p.options.map(o=>{const pct=total?Math.round((o.votes||0)/total*100):0;return `<div style="margin-bottom:8px"><div style="display:flex;justify-content:space-between;font-size:13.5px;margin-bottom:3px"><span>${esc(o.text)}</span><span style="color:var(--accent)">${o.votes||0} · ${pct}%</span></div><div style="background:#0d1525;border-radius:6px;height:9px;overflow:hidden"><div style="width:${pct}%;height:9px;background:var(--accent)"></div></div></div>`;}).join("")+`</div>`:"";
  return `<h2>Sorğu (Poll)</h2><div class="sub">Oxucular əsas səhifədə səs verir. Yeni sorğu yaratdıqda səslər sıfırlanır.</div>
   <div class="panel" style="max-width:620px">
     <div id="pollMsg" style="display:none;margin-bottom:10px;padding:10px 14px;border-radius:8px"></div>
     <label>Sual</label><input class="f" id="pollQ" placeholder="Sizcə kim qalib gələcək?" value="${esc(p.question||'')}">
     <label>Cavablar (hər sətirdə bir cavab, 2-6 ədəd)</label><textarea class="f" id="pollOpts" rows="5" placeholder="Qarabağ&#10;Neftçi&#10;Heç-heçə">${esc(opts)}</textarea>
     <label style="display:flex;align-items:center;gap:8px;margin-top:14px;color:var(--txt)"><input type="checkbox" id="pollActive" ${p.active?'checked':''} style="width:auto"> Sorğunu göstər (aktiv)</label>
     <button class="btn" onclick="savePoll()">Yadda saxla</button></div>${results}`;}
function pollMsg(t,ok){const m=document.getElementById("pollMsg");if(!m)return;m.style.display="block";m.textContent=t;m.style.background=ok?"rgba(0,230,168,.15)":"rgba(255,61,113,.15)";m.style.color=ok?"var(--accent)":"var(--accent2)";setTimeout(()=>{m.style.display="none";},4000);}
async function savePoll(){const q=document.getElementById("pollQ").value.trim();
  const options=document.getElementById("pollOpts").value.split("\n").map(s=>s.trim()).filter(Boolean);
  if(options.length<2){pollMsg("Ən azı 2 cavab lazımdır",false);return;}
  const payload={password:PW,question:q,options,active:document.getElementById("pollActive").checked};
  const r=await (await fetch("/api/poll/set",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)})).json();
  if(r.ok){pollMsg("✓ Yadda saxlanıldı",true);try{POLL_DATA=await (await fetch("/api/poll")).json();}catch(e){}dashRender();}else pollMsg("Xəta baş verdi",false);}
function dashAd(){const a=AD_DATA||{};
  return `<h2>Reklam</h2><div class="sub">Saytın əsas səhifəsində göstəriləcək banner</div>
   <div class="panel" style="max-width:620px">
     <div id="adMsg" style="display:none;margin-bottom:10px;padding:10px 14px;border-radius:8px"></div>
     ${a.image?`<img src="${esc(a.image)}" style="max-width:100%;border-radius:10px;margin-bottom:12px">`:''}
     <label>Banner şəkli (yüklə)</label><input class="f" id="adImg" type="file" accept="image/*">
     <label>...və ya şəkil linki (URL)</label><input class="f" id="adUrl" placeholder="https://...jpg" value="${a.image&&String(a.image).startsWith('http')?esc(a.image):''}">
     <label>Keçid linki (reklam haraya aparsın)</label><input class="f" id="adLink" placeholder="https://..." value="${esc(a.link||'')}">
     <label style="display:flex;align-items:center;gap:8px;margin-top:14px;color:var(--txt)"><input type="checkbox" id="adActive" ${a.active?'checked':''} style="width:auto"> Reklamı göstər (aktiv)</label>
     <button class="btn" onclick="saveAd()">Yadda saxla</button></div>`;}
function adMsg(t,ok){const m=document.getElementById("adMsg");if(!m)return;m.style.display="block";m.textContent=t;m.style.background=ok?"rgba(0,230,168,.15)":"rgba(255,61,113,.15)";m.style.color=ok?"var(--accent)":"var(--accent2)";setTimeout(()=>{m.style.display="none";},4000);}
async function saveAd(){const fileEl=document.getElementById("adImg");let image_data="";
  if(fileEl.files&&fileEl.files[0]){if(fileEl.files[0].size>5*1024*1024){adMsg("Şəkil 5MB-dan kiçik olmalıdır",false);return;}
    image_data=await new Promise(r=>{const fr=new FileReader();fr.onload=()=>r(fr.result);fr.readAsDataURL(fileEl.files[0]);});}
  const payload={password:PW,image_data,image:document.getElementById("adUrl").value.trim(),link:document.getElementById("adLink").value.trim(),active:document.getElementById("adActive").checked};
  const r=await (await fetch("/api/ad/set",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)})).json();
  if(r.ok){adMsg("✓ Yadda saxlanıldı",true);try{AD_DATA=await (await fetch("/api/ad")).json();}catch(e){}dashRender();}else adMsg("Xəta baş verdi",false);}
function kpi(k,v,c){return `<div class="kpi"><div class="k">${k}</div><div class="v" style="color:${c||'var(--txt)'}">${v||0}</div></div>`;}
function dashOverview(){const d=DASH||{},t=d.totals||{};
  const daily=d.daily||[],max=Math.max(1,...daily.map(x=>x.count));
  const bars=daily.map(x=>`<div style="flex:1"><div class="bar" style="height:${Math.round(x.count/max*120)}px" title="${x.count}"></div><div class="bl">${(x.date||'').slice(5)}</div></div>`).join("");
  const top=(d.top||[]).filter(a=>a.views||a.shares).slice(0,6).map(a=>`<tr><td>${esc(a.title||a.id)}</td><td style="text-align:center;color:var(--accent)">${a.views}</td><td style="text-align:center;color:var(--gold)">${a.shares}</td></tr>`).join("");
  const geo=(d.geo||[]).slice(0,7).map(g=>`<tr><td>${esc(g.loc)}</td><td style="text-align:right;color:var(--accent)">${g.count}</td></tr>`).join("");
  const rc=(d.recentComments||[]).slice(0,5).map(c=>`<div style="border-bottom:1px solid var(--line);padding:7px 0"><b style="color:var(--accent)">${esc(c.name||'Anonim')}</b> <small style="color:var(--muted)">${fmtTime(c.date)} · ${esc((c.title||'').slice(0,40))}</small><div style="color:#c5d3ec;font-size:13px">${esc(c.text)}</div></div>`).join("");
  return `<h2>İcmal</h2><div class="sub">Son yeniləmə: ${fmtTime(d.updated)}</div>
   <div class="kpis">${kpi("Ümumi oxunma",t.views,"var(--accent)")}${kpi("Paylaşım",t.shares,"var(--gold)")}${kpi("Şərhlər",t.comments)}${kpi("Mesajlar",t.messages,"var(--accent2)")}${kpi("Sizin xəbərlər",t.myArticles)}${kpi("Canlı xəbərlər",t.liveArticles)}${kpi("Məkanlar",t.locations)}</div>
   <div class="panel"><h3>Son 14 gün — oxunma</h3><div class="bars">${bars||'<span style="color:var(--muted)">Məlumat yoxdur</span>'}</div></div>
   <div class="dgrid">
     <div class="panel"><h3>Ən çox oxunan</h3><table class="dtable"><thead><tr><th>Xəbər</th><th>Oxunma</th><th>Paylaşım</th></tr></thead><tbody>${top||'<tr><td colspan=3 style="color:var(--muted)">Hələ yoxdur</td></tr>'}</tbody></table></div>
     <div class="panel"><h3>🌍 Oxucuların yeri</h3><table class="dtable"><tbody>${geo||'<tr><td style="color:var(--muted)">Hələ yoxdur</td></tr>'}</tbody></table></div></div>
   <div class="panel"><h3>Son şərhlər</h3>${rc||'<span style="color:var(--muted)">Hələ şərh yoxdur</span>'}</div>`;}
function dashArticles(){const opts=CATS.filter(c=>c!=="Hamısı").map(c=>`<option>${c}</option>`).join("");
  return `<h2>Xəbərlərim</h2><div class="sub">Öz xəbərlərinizi əlavə edin, redaktə və ya silin.</div>
   <div class="panel" style="max-width:640px">
     <div id="amsg" style="display:none;margin-bottom:10px;padding:10px 14px;border-radius:8px"></div>
     <label>Başlıq *</label><input class="f" id="aTitle" placeholder="Başlıq">
     <div class="row2"><div><label>Kateqoriya</label><select class="f" id="aCat">${opts}</select></div><div><label>Müəllif</label><input class="f" id="aAuthor" value="Redaksiya"></div></div>
     <label>Şəkil (kompüterdən yüklə)</label><input class="f" id="aImage" type="file" accept="image/*">
     <label>Qısa təsvir</label><textarea class="f" id="aSummary" style="min-height:60px"></textarea>
     <label>Tam mətn</label><textarea class="f" id="aBody"></textarea>
     <label>Mənbə linki (istəyə bağlı)</label><input class="f" id="aLink" placeholder="https://...">
     <button class="btn" id="aSubmit" onclick="saveArticle()">Xəbəri yayımla</button></div>
   <div class="panel"><h3>Əlavə etdiyim xəbərlər</h3><div class="mylist" id="myList"></div></div>`;}
function dashStats(){const d=DASH||{},items=d.top||[];
  const catmap={};items.forEach(it=>{const a=ALL.find(x=>x.id===it.id);const c=a?a.category:"Digər";catmap[c]=(catmap[c]||0)+(it.views||0);});
  const cats=Object.entries(catmap).filter(c=>c[1]).sort((a,b)=>b[1]-a[1]);const cmax=Math.max(1,...cats.map(c=>c[1]));
  const catbars=cats.map(([c,v])=>`<div style="margin-bottom:9px"><div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px"><span>${esc(c)}</span><span style="color:var(--accent)">${v}</span></div><div style="background:#0d1525;border-radius:5px;height:9px"><div style="width:${Math.round(v/cmax*100)}%;height:9px;background:var(--accent);border-radius:5px"></div></div></div>`).join("");
  const rows=items.filter(i=>i.views||i.shares).map(i=>`<tr><td>${esc(i.title||i.id)}</td><td style="text-align:center;color:var(--accent)">${i.views}</td><td style="text-align:center;color:var(--gold)">${i.shares}</td></tr>`).join("");
  const geo=(d.geo||[]).map(g=>`<tr><td>${esc(g.loc)}</td><td style="text-align:right;color:var(--accent)">${g.count}</td></tr>`).join("");
  return `<h2>Statistika</h2><div class="sub">Oxunma və paylaşım göstəriciləri</div>
   <div class="dgrid"><div class="panel"><h3>Fənlər üzrə oxunma</h3>${catbars||'<span style="color:var(--muted)">Yoxdur</span>'}</div>
     <div class="panel"><h3>🌍 Bütün məkanlar</h3><table class="dtable"><tbody>${geo||'<tr><td style="color:var(--muted)">Yoxdur</td></tr>'}</tbody></table></div></div>
   <div class="panel"><h3>Xəbərlər üzrə</h3><table class="dtable"><thead><tr><th>Xəbər</th><th>Oxunma</th><th>Paylaşım</th></tr></thead><tbody>${rows||'<tr><td colspan=3 style="color:var(--muted)">Yoxdur</td></tr>'}</tbody></table></div>`;}
function dashComments(){const list=(DASH||{}).recentComments||[];
  return `<h2>Şərhlər</h2><div class="sub">Son şərhlər — uyğunsuzu silə bilərsiniz</div>
   <div class="panel">${list.length?list.map((c,i)=>`<div style="border-bottom:1px solid var(--line);padding:10px 0;display:flex;justify-content:space-between;gap:12px">
     <div><b style="color:var(--accent)">${esc(c.name||'Anonim')}</b> <small style="color:var(--muted)">${fmtTime(c.date)} · ${esc((c.title||'').slice(0,50))}</small><div style="color:#c5d3ec;font-size:14px;margin-top:3px">${esc(c.text)}</div></div>
     <button class="del" onclick="delCommentIdx(${i})">Sil</button></div>`).join(""):'<span style="color:var(--muted)">Hələ şərh yoxdur</span>'}</div>`;}
async function delCommentIdx(i){const c=((DASH||{}).recentComments||[])[i];if(!c||!confirm("Şərh silinsin?"))return;
  await fetch("/api/comment/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:PW,id:c.id,date:c.date,text:c.text})});
  await dashLoad();dashRender();}
function dashContacts(){const list=(DASH||{}).recentContacts||[];
  return `<h2>Mesajlar</h2><div class="sub">Əlaqə formundan gələn mesajlar</div>
   <div class="panel">${list.length?list.map(m=>`<div style="border-bottom:1px solid var(--line);padding:12px 0">
     <div style="display:flex;justify-content:space-between"><b style="color:var(--accent)">${esc(m.name||'Anonim')}</b><small style="color:var(--muted)">${fmtTime(m.date)}</small></div>
     ${m.phone?`<div style="color:var(--gold);font-size:13px;margin:3px 0">📞 ${esc(m.phone)}</div>`:''}
     ${m.message?`<p style="color:#c5d3ec;font-size:14px;margin:6px 0;white-space:pre-wrap">${esc(m.message)}</p>`:''}
     ${m.image?`<a href="${esc(m.image)}" target="_blank" rel="noopener"><img src="${esc(m.image)}" style="max-width:200px;border-radius:8px;margin-top:6px"></a>`:''}</div>`).join(""):'<span style="color:var(--muted)">Hələ mesaj yoxdur</span>'}</div>`;}
function dashSources(){const d=DASH||{},s=d.sources||[];
  const rows=s.map(x=>`<tr><td>${esc(x.name)}</td><td style="color:var(--muted)">${esc(x.type||'')}</td><td style="text-align:center">${x.count||0}</td><td style="text-align:center;color:${x.ok?'var(--accent)':'var(--accent2)'}">${x.ok?'✓ işləyir':'✗ problem'}</td></tr>`).join("");
  return `<h2>Mənbələr</h2><div class="sub">Mənbələrin vəziyyəti · Canlı xəbərlər: ${(d.totals||{}).liveArticles||0} · Son yeniləmə: ${fmtTime(d.updated)}</div>
   <div class="panel"><table class="dtable"><thead><tr><th>Mənbə</th><th>Növ</th><th>Sayı</th><th>Status</th></tr></thead><tbody>${rows||'<tr><td colspan=4 style="color:var(--muted)">Yoxdur</td></tr>'}</tbody></table></div>`;}
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
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button onclick="pinArticle('${i.id}')" style="background:var(--card);border:1px solid ${i.pinned?'var(--gold)':'var(--line)'};color:${i.pinned?'var(--gold)':'var(--muted)'};padding:7px 12px;border-radius:8px;cursor:pointer;font-weight:700;font-size:12px">📌 ${i.pinned?'Sabitlənib':'Sabitlə'}</button>
      <button onclick="editArticle('${i.id}')" style="background:var(--card);border:1px solid var(--line);color:var(--txt);padding:7px 12px;border-radius:8px;cursor:pointer;font-weight:700;font-size:12px">Düzəliş</button>
      <button class="del" onclick="delArticle('${i.id}')">Sil</button></div></div>`).join(""):`<p style="color:var(--muted);font-size:13px;margin-top:8px">Hələ xəbər yoxdur.</p>`;}
async function pinArticle(id){await fetch("/api/article/pin",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:PW,id})});await load();renderMyList();}
async function delArticle(id){if(!confirm("Silinsin?"))return;
  await fetch("/api/article/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:PW,id})});await load();renderMyList();}
function selectCat(c){CURRENT=c;SEARCH="";SHOWN=18;if(c!=="⭐ Mənim")FAV_EDIT=false;if(c!=="Cüdo"&&JUDO.t){clearTimeout(JUDO.t);JUDO.t=null;}document.getElementById("q").value="";window.scrollTo({top:0,behavior:"smooth"});buildTabs();render();buildTicker();}
let st;function onSearch(){SEARCH=document.getElementById("q").value;SHOWN=18;clearTimeout(st);st=setTimeout(()=>{render();buildTicker();},250);}
let SHOWN=18;function showMore(){SHOWN+=18;render();}
window.addEventListener("scroll",()=>{const b=document.getElementById("toTop");if(b)b.classList.toggle("show",window.scrollY>700);});
document.addEventListener("keydown",e=>{if(e.key==="Escape"){closeModal();closeAdmin();}});
restoreAdminSession();load().then(openFromHash);window.addEventListener("hashchange",openFromHash);setInterval(load,60000);
if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(()=>{});}
</script></body></html>"""


if __name__ == "__main__":
    main()
