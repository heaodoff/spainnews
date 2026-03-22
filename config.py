"""Configuration for Spain News Bot."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent / ".env")

# Telegram
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@spainnewsletter")

# OpenAI
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Scheduler — 4 times a day (9:00, 12:00, 16:00, 20:00 Madrid time)
SCHEDULE_HOURS = [9, 12, 16, 20]
TIMEZONE = "Europe/Madrid"

# How many articles to post per run
MAX_ARTICLES_PER_RUN = 3

# Admin approval
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])
STRIPE_LINK = os.environ["STRIPE_LINK"]

# Database
DB_PATH = os.path.join(os.path.dirname(__file__), "news.db")

# RSS Sources — official + news
RSS_FEEDS = [
    # === Official sources ===
    {
        "name": "BOE (Boletín Oficial del Estado)",
        "url": "https://www.boe.es/rss/boe.php?s=1",
        "category": "legislation",
        "priority": 1,
    },
    {
        "name": "BOE — Disposiciones",
        "url": "https://www.boe.es/rss/boe.php?s=2",
        "category": "legislation",
        "priority": 1,
    },
    # === News — Economy & Real Estate ===
    {
        "name": "El País — Economía",
        "url": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/economia/portada",
        "category": "economy",
        "priority": 2,
    },
    {
        "name": "La Vanguardia — Economía",
        "url": "https://www.lavanguardia.com/rss/economia.xml",
        "category": "economy",
        "priority": 2,
    },
    {
        "name": "Expansión — Economía",
        "url": "https://e00-expansion.uecdn.es/rss/economia.xml",
        "category": "real_estate",
        "priority": 1,
    },
    {
        "name": "20 Minutos — Economía",
        "url": "https://www.20minutos.es/rss/economia/",
        "category": "economy",
        "priority": 2,
    },
    # === Immigration & Expats ===
    {
        "name": "The Local Spain",
        "url": "https://feeds.thelocal.com/rss/es",
        "category": "expats",
        "priority": 1,
    },
    {
        "name": "Europa Press — Economía",
        "url": "https://www.europapress.es/rss/rss.aspx?ch=136",
        "category": "economy",
        "priority": 2,
    },
    # === Tax & Finance ===
    {
        "name": "Cinco Días",
        "url": "https://cincodias.elpais.com/rss/cincodias/portada.xml",
        "category": "finance",
        "priority": 2,
    },
    # === Tourism ===
    {
        "name": "Hosteltur",
        "url": "https://www.hosteltur.com/feed",
        "category": "tourism",
        "priority": 2,
    },
    # === Canary Islands ===
    {
        "name": "20 Minutos — Canarias",
        "url": "https://www.20minutos.es/rss/canarias/",
        "category": "canarias",
        "priority": 1,
    },
    {
        "name": "20 Minutos — Las Palmas",
        "url": "https://www.20minutos.es/rss/canarias/las-palmas/",
        "category": "canarias",
        "priority": 2,
    },
    {
        "name": "Google News — Canarias Economía",
        "url": "https://news.google.com/rss/search?q=canarias+islas+economia+turismo+inmobiliaria&hl=es&gl=ES&ceid=ES:es",
        "category": "canarias",
        "priority": 1,
    },
    {
        "name": "Google News — Canarias Inmigración",
        "url": "https://news.google.com/rss/search?q=canarias+inmigracion+vivienda+alquiler+extranjeros&hl=es&gl=ES&ceid=ES:es",
        "category": "canarias",
        "priority": 1,
    },
    # === General Spain news ===
    {
        "name": "20 Minutos — España",
        "url": "https://www.20minutos.es/rss/",
        "category": "general",
        "priority": 3,
    },
    {
        "name": "El País — España",
        "url": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/espana/portada",
        "category": "general",
        "priority": 3,
    },
    {
        "name": "La Vanguardia — Vida",
        "url": "https://www.lavanguardia.com/rss/vida.xml",
        "category": "lifestyle",
        "priority": 3,
    },
]

# Keywords for filtering relevant articles (Spanish + English)
KEYWORDS = [
    # Spanish
    "inmigración", "extranjero", "residencia", "visado", "NIE", "permiso",
    "impuesto", "IRPF", "IVA", "fiscal", "tributario", "hacienda",
    "vivienda", "hipoteca", "alquiler", "inmobiliaria", "propiedad",
    "inversión", "inversor", "golden visa", "nómada digital",
    "turismo", "turista", "vuelo", "hotel",
    "ley", "decreto", "normativa", "regulación", "reforma",
    "autónomo", "empresa", "emprendedor", "sociedad limitada",
    "seguridad social", "sanidad", "empadronamiento",
    "Beckham", "modelo 720", "modelo 100",
    # Canary Islands
    "Canarias", "Tenerife", "Gran Canaria", "Lanzarote", "Fuerteventura",
    "La Palma", "La Gomera", "El Hierro", "Las Palmas", "Santa Cruz",
    "canario", "insular", "archipiélago",
    # Weather & natural events
    "tormenta", "borrasca", "temporal", "huracán", "ciclón", "lluvia",
    "viento", "calima", "ola de calor", "incendio", "inundación",
    "alerta", "emergencia", "AEMET", "fenómeno", "nieve", "granizo",
    "storm", "hurricane", "flood", "wildfire", "heatwave", "weather alert",
    # Culture, events & lifestyle
    "carnaval", "fiesta", "festival", "feria", "procesión", "Semana Santa",
    "reina", "rey", "familia real", "celebración", "tradición",
    "carnival", "festival", "royal family", "tradition", "celebration",
    # Safety & incidents
    "policía", "guardia civil", "accidente", "terremoto", "seísmo",
    "evacuación", "rescate", "apagón", "corte de luz", "huelga",
    "police", "earthquake", "blackout", "strike", "evacuation",
    # Transport & infrastructure
    "aeropuerto", "puerto", "carretera", "tráfico", "transporte",
    "AVE", "Renfe", "AENA", "autopista", "metro", "guagua",
    "airport", "ferry", "highway", "train", "transport",
    # Health & education
    "hospital", "médico", "SCS", "educación", "colegio", "universidad",
    "health", "school", "university",
    # English
    "immigration", "residence", "visa", "foreigner",
    "tax", "property", "real estate", "rental", "mortgage",
    "investment", "investor", "digital nomad",
    "tourism", "tourist",
    "law", "regulation", "decree",
    "self-employed", "healthcare", "social security",
    "Canary Islands", "Tenerife", "Gran Canaria",
    # General Spain
    "España", "Spain", "español", "Spanish",
]
