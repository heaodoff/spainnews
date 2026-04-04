"""AI-powered editorial pipeline using OpenAI API.

New flow: score article (1-5) → decide SKIP/SHORT/FULL → generate post + comment.
"""
import logging
import re

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

client = OpenAI(api_key=OPENAI_API_KEY)

# New categories from the editorial prompt
CATEGORY_MAP = {
    "недвижимость": "🏠 Недвижимость",
    "деньги": "💶 Деньги",
    "иммиграция": "🛂 Иммиграция",
    "законы": "⚖️ Законы",
    "быт": "🛒 Быт и цены",
}

# Legacy category mapping (from RSS feed categories)
LEGACY_TO_NEW = {
    "legislation": "⚖️ Законы",
    "economy": "💶 Деньги",
    "real_estate": "🏠 Недвижимость",
    "expats": "🛂 Иммиграция",
    "finance": "💶 Деньги",
    "tourism": "🛒 Быт и цены",
    "canarias": "🏠 Недвижимость",
}


def is_urgent(article: dict) -> bool:
    """
    AI check: is this breaking news that should be posted immediately?
    Very strict — only truly urgent items.
    """
    prompt = f"""Ты — редактор новостного канала для иностранцев в Испании.

Это СРОЧНАЯ новость, которую НУЖНО опубликовать НЕМЕДЛЕННО? Ответь ОДНИМ словом: ДА или НЕТ.

СРОЧНО (ДА) — только если:
- Новый закон или указ который СЕЙЧАС вступает в силу и напрямую влияет на иностранцев, налоги, визы, ВНЖ
- Резкое изменение налоговых ставок, новые обязательства с конкретной датой
- Отмена или введение golden visa, изменения визового режима
- Экстренные изменения в иммиграционных правилах
- Резкий обвал/рост цен на недвижимость (>10%)
- Отмена рейсов, закрытие границ, чрезвычайные ситуации для туристов
- Новые штрафы или запреты для иностранцев/туристов с немедленным действием

НЕ СРОЧНО (НЕТ) — всё остальное:
- Обычные экономические новости, прогнозы, аналитика
- Плановые изменения с долгим сроком вступления
- Обсуждения законопроектов (ещё не приняты)
- Рыночные тренды, статистика
- Всё что может подождать до следующего планового выпуска

Заголовок: {article['title']}
Содержание: {article['summary'][:500]}
Источник: {article['source']}

Ответ (только ДА или НЕТ):"""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=5,
        )
        answer = response.choices[0].message.content.strip().upper()
        is_yes = answer.startswith("ДА") or answer.startswith("DA") or answer == "YES"
        if is_yes:
            logger.info("🚨 URGENT article detected: %s", article["title"][:70])
        return is_yes
    except Exception:
        logger.exception("Error in urgency check")
        return False


def check_needs_approval(article: dict, processed: dict) -> dict:
    """
    AI check: should this post be sent for admin approval?
    Returns dict with keys: needs_approval (bool), reason (str), recommendation (str),
    suggest_service (bool), service_reason (str), cta_text (str).
    """
    prompt = f"""Ты управляешь публикацией новостей в Telegram-канал для иностранцев в Испании.

Определи, нужно ли отправить эту новость на согласование администратору.

Считать новость ВАЖНОЙ (нужно согласование), если она:
- сильно влияет на аудиторию (иностранцы, арендаторы, покупатели, инвесторы)
- касается практических действий (что-то надо сделать, оформить, подать)
- связана с: недвижимостью, регистрацией квартир, VV (vivienda vacacional), налогами, бизнесом, документами, миграцией, лицензиями, штрафами, новыми правилами, законами, разрешениями

ОБЫЧНАЯ новость (не нужно согласование):
- общие экономические тренды, статистика, рыночные обзоры
- новости без прямого практического влияния
- культурные, туристические новости

Заголовок: {article['title']}
Содержание: {article['summary'][:500]}
Источник: {article['source']}
Оценка важности: {processed.get('score', 3)}/5

Суть нашей услуги: мы объясняем, как сделать всё самому пошагово — зарегистрировать квартиру, подготовить документы, пройти процедуру без ошибок.

Ответь СТРОГО в формате:
NEEDS_APPROVAL: ДА или НЕТ
REASON: почему важная (или почему обычная), 1 строка
RECOMMENDATION: Просто новость / Новость + мягкий CTA / Новость + продажа услуги / Не публиковать
SUGGEST_SERVICE: ДА или НЕТ
SERVICE_REASON: почему стоит/не стоит добавлять услугу, 1 строка
CTA: текст мягкого CTA если SUGGEST_SERVICE=ДА (или NONE)"""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
        )
        text = response.choices[0].message.content.strip()

        needs = "ДА" in (re.search(r"NEEDS_APPROVAL:\s*(\S+)", text) or type("", (), {"group": lambda s, x: "НЕТ"})()).group(1).upper()
        reason_m = re.search(r"REASON:\s*(.+)", text)
        rec_m = re.search(r"RECOMMENDATION:\s*(.+)", text)
        svc_m = re.search(r"SUGGEST_SERVICE:\s*(\S+)", text)
        svc_reason_m = re.search(r"SERVICE_REASON:\s*(.+)", text)
        cta_m = re.search(r"CTA:\s*(.+)", text)

        suggest_svc = svc_m and "ДА" in svc_m.group(1).upper()
        cta = cta_m.group(1).strip() if cta_m and cta_m.group(1).strip() != "NONE" else ""

        return {
            "needs_approval": needs,
            "reason": reason_m.group(1).strip() if reason_m else "",
            "recommendation": rec_m.group(1).strip() if rec_m else "Просто новость",
            "suggest_service": bool(suggest_svc),
            "service_reason": svc_reason_m.group(1).strip() if svc_reason_m else "",
            "cta_text": cta if suggest_svc else "",
        }
    except Exception:
        logger.exception("Error in approval check")
        return {"needs_approval": False, "reason": "error", "recommendation": "Просто новость",
                "suggest_service": False, "service_reason": "", "cta_text": ""}


def process_article(article: dict) -> dict | None:
    """
    Unified editorial pipeline:
    1) Score importance (1-5)
    2) Decide: SKIP / SHORT / FULL
    3) Pick category
    4) Generate post (and comment if FULL)
    5) Suggest image description

    Returns None if SKIP, otherwise dict with keys:
    - format: "SHORT" or "FULL"
    - short_post: the channel post text
    - detailed_comment: comment text (only for FULL, None for SHORT)
    - image_headline: headline for image generation
    - image_description: AI-suggested image description
    - category: emoji + category name
    - source, url, title
    """
    image_url = article.get("image_url", "")
    image_note = f"\nИзображение из статьи: {image_url}" if image_url else ""

    prompt = f"""Ты — главный редактор Telegram-канала для иностранцев, живущих в Испании.

---
## АУДИТОРИЯ
- иностранцы в Испании
- арендаторы
- покупатели недвижимости
- инвесторы
- люди, планирующие переезд
---
## ШАГ 1 — ОЦЕНКА ВАЖНОСТИ
Главный вопрос: "Человек, живущий в Испании, увидит это и скажет 'ого, мне надо это знать'?"

5 — СРОЧНО: закон вступает в силу, ЧП, эвакуация, визовые изменения, стихийные бедствия
4 — ВАЖНО: новые цены/штрафы с конкретной датой, забастовки (аэропорты, транспорт), погодные аномалии, крупные изменения в быту, законопроекты об аренде/налогах
3 — ИНТЕРЕСНО: культурные события (карнавал, фестивали, Semana Santa), тренды с конкретными цифрами, инфраструктурные изменения (дороги, транспорт), необычные факты о жизни в Испании
2 — СЛАБО: корпоративные отчёты, абстрактная политика без влияния на быт, общие тренды без цифр, биржевые новости, спортивные события, повторы уже известных фактов, криминальная хроника без влияния на безопасность аудитории
1 — МУСОР: реклама, не про Испанию, пресс-релизы компаний, мнения без фактов, жёлтая пресса (убийства, насилие, скандалы знаменитостей)

⚠️ ВАЖНО — НЕ ПУБЛИКОВАТЬ:
- Криминальную хронику (убийства, изнасилования, ограбления) — если это не массовое ЧП или угроза безопасности района
- Жёлтую прессу (скандалы, сплетни, шокирующие но бесполезные факты)
- Новости про корриду, бои быков — это не помогает аудитории
- Военные новости без прямого влияния на жизнь в Испании

ПРИМЕРЫ:
✅ 5: "Новый закон аренды вступает в силу с 1 апреля" → FULL
✅ 4: "Забастовка персонала в 12 аэропортах на Пасху" → FULL
✅ 3: "Карнавал Санта-Крус — программа 2026" → SHORT
❌ 2: "Рост ВВП Испании замедлился на 0.1%" → SKIP
❌ 2: "Бывший матадор погиб от быка" → SKIP (жёлтая пресса)
❌ 2: "Задержаны двое за изнасилование" → SKIP (криминальная хроника)
❌ 1: "Philip Morris открыл офис в Кремниевой долине" → SKIP
---
## ШАГ 2 — РЕШЕНИЕ
1–2 → OUTPUT: SKIP
3 → SHORT
4–5 → FULL
---
## ШАГ 3 — КАТЕГОРИЯ
Выбери одну:
🏠 Недвижимость
💶 Деньги
🛂 Иммиграция
⚖️ Законы
🛒 Быт и цены
🌪 Погода и стихия
🎭 Культура и события
🚨 Происшествия
🚗 Транспорт
🏥 Здоровье
---
## ШАГ 4 — ИЗОБРАЖЕНИЕ (для DALL-E)
Опиши СЦЕНУ для фоновой фотографии (НЕ текст, только визуал):
- что изображено: город, здание, документы, деньги, рынок и т.д.
- настроение: СВЕТЛОЕ, тёплое, средиземноморское, яркое
- пример: "white Mediterranean apartment building, blue sky, palm trees, golden sunlight"
- пример: "colorful Spanish market with fresh produce, warm natural light"
- НЕ пиши мрачные/тёмные описания — только светлые и приятные
- НЕ пиши текст, заголовки, слова — только описание сцены на АНГЛИЙСКОМ
---
## ШАГ 5 — ГЕНЕРАЦИЯ

### Если SHORT:
POST:
[эмодзи] Короткий заголовок

1–2 предложения сути

Почему это важно:
• пункт
• пункт

Источник: [название]

#хэштег (один, по категории: #недвижимость #налоги #иммиграция #законы #быт #погода #транспорт #происшествия #культура #здоровье)

### Если FULL:
POST:
[эмодзи] Короткий сильный заголовок

1–2 предложения сути новости.

Источник: [название]
👇 Полный разбор — в комментарии

#хэштег (один, по категории)

COMMENT:
📰 Что произошло
(Объясни новость так, как будто рассказываешь другу, который ничего об этом не слышал. Начни с самого главного: что конкретно случилось? Кто принял решение / что изменилось / что произошло? Потом дай все ключевые детали: цифры, даты, имена, суммы. Минимум 4–6 предложений. Человек должен полностью понять новость, не открывая оригинал)

🔍 Почему это важно
(Объясни контекст. Почему это произошло именно сейчас? Что было до этого? Какая проблема стоит за этой новостью? Если это закон — какую проблему он решает. Если это происшествие — насколько это типично или необычно. 3–4 предложения)

🏠 Как это касается тебя
• пункт (конкретный пример: что изменится в деньгах, документах, аренде, работе, быту)
• пункт
• пункт
(Минимум 3 пункта. Каждый пункт — конкретное последствие, а не абстракция)

📌 Итог одной фразой
(Одно предложение — суть для тех, кто не хочет читать всё)
---
## СТИЛЬ И ТОН
- ОБЯЗАТЕЛЬНО пиши ВЕСЬ текст поста и комментария ТОЛЬКО НА РУССКОМ ЯЗЫКЕ
- даже если оригинал на английском или испанском — ПЕРЕВОДИ на русский
- ТОН: как будто объясняешь другу. Живо, по-человечески, без канцелярита
- НЕ пиши: "это может повлиять на потребителей" → пиши: "это значит, что ты будешь платить больше"
- НЕ пиши: "данная мера затронет резидентов" → пиши: "если ты живёшь в Испании — это касается тебя"
- обращайся на "ты", а не на "вы"
- коротко, без воды
- не как статья — как Telegram-пост от человека
- без фраз "для русскоязычных иммигрантов"
- писать как: "для тех, кто живёт в Испании"
- короткие абзацы, списки вместо текста
- все цифры, суммы, проценты, даты из оригинала
- испанские термины с переводом: IRPF (подоходный налог)
- НЕ придумывай информацию которой нет в статье
---

НОВОСТЬ:
Источник: {article['source']}
Заголовок: {article['title']}
Содержание: {article['summary']}{image_note}

---
ОТВЕТЬ СТРОГО В ФОРМАТЕ:

SCORE: [число 1-5]
DECISION: [SKIP / SHORT / FULL]
CATEGORY: [категория с эмодзи]
IMAGE: [описание сцены на английском для DALL-E, без текста]

[Если не SKIP:]
===POST===
[текст поста]
===COMMENT===
[текст комментария — только для FULL, пропусти для SHORT]"""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2500,
        )

        text = response.choices[0].message.content.strip()
        logger.debug("AI response:\n%s", text[:500])

        # Parse SCORE
        score_match = re.search(r"SCORE:\s*(\d)", text)
        score = int(score_match.group(1)) if score_match else 3

        # Parse DECISION
        decision_match = re.search(r"DECISION:\s*(SKIP|SHORT|FULL)", text)
        decision = decision_match.group(1) if decision_match else "FULL"

        # Parse CATEGORY
        category_match = re.search(r"CATEGORY:\s*(.+)", text)
        category = category_match.group(1).strip() if category_match else LEGACY_TO_NEW.get(article["category"], "💶 Деньги")

        # Parse IMAGE description
        image_match = re.search(r"IMAGE:\s*(.+?)(?:\n|===)", text, re.DOTALL)
        image_description = image_match.group(1).strip() if image_match else ""

        logger.info("Article score=%d decision=%s: %s", score, decision, article["title"][:60])

        # SKIP — not interesting enough
        if decision == "SKIP" or score <= 2:
            logger.info("Skipped (score=%d): %s", score, article["title"][:60])
            return None

        # Parse POST
        post_text = ""
        if "===POST===" in text:
            post_part = text.split("===POST===")[1]
            if "===COMMENT===" in post_part:
                post_text = post_part.split("===COMMENT===")[0].strip()
            else:
                post_text = post_part.strip()
        else:
            # Fallback: use everything after the header lines
            logger.warning("No ===POST=== marker, using fallback")
            post_text = text

        # Parse COMMENT (only for FULL)
        comment_text = None
        if decision == "FULL" and "===COMMENT===" in text:
            comment_text = text.split("===COMMENT===")[1].strip()

        # Replace plain "Источник: X" with markdown link
        post_text = re.sub(
            r"Источник:\s*(.+)",
            f"Источник: [{article['source']}]({article['url']})",
            post_text,
        )

        # Extract headline for image generation
        image_headline = post_text.split("\n")[0].strip()
        image_headline = re.sub(r"^[^\w]*", "", image_headline)  # strip leading emoji/special chars
        image_headline = image_headline.replace("**", "")

        return {
            "format": decision,
            "short_post": post_text,
            "detailed_comment": comment_text,
            "image_headline": image_headline,
            "image_description": image_description,
            "source": article["source"],
            "url": article["url"],
            "title": article["title"],
            "category": category,
            "score": score,
        }

    except Exception:
        logger.exception("Error processing article: %s", article["title"])
        return None
