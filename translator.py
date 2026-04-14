"""AI-powered editorial pipeline using OpenAI API.

New flow: score article (1-5) → decide SKIP/SHORT/FULL → generate post + comment.
"""
import logging
import re

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL
from article_parser import fetch_article_text
from database import get_recent_topics

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

# Category → hashtag (for post footer)
CATEGORY_HASHTAGS = {
    "🏠 Недвижимость": "#недвижимость",
    "💶 Деньги": "#налоги",
    "🛂 Иммиграция": "#иммиграция",
    "⚖️ Законы": "#законы",
    "🛒 Быт и цены": "#быт",
    "🌪 Погода и стихия": "#погода",
    "🎭 Культура и события": "#культура",
    "🚨 Происшествия": "#происшествия",
    "🚗 Транспорт": "#транспорт",
    "🏥 Здоровье": "#здоровье",
}


def _category_to_hashtag(category: str) -> str:
    """Return a single hashtag for the given category, or empty string."""
    if not category:
        return ""
    for key, tag in CATEGORY_HASHTAGS.items():
        if key in category or key.replace(" ", "").lower() in category.lower():
            return tag
    return ""

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

    # Try to fetch the FULL article body (RSS summary is usually 1-2 sentences,
    # which isn't enough to extract concrete facts, € amounts, deadlines).
    full_text = fetch_article_text(article.get("url", ""))
    content = full_text if len(full_text) > len(article.get("summary", "")) else article.get("summary", "")
    if not content:
        content = article.get("summary", "")

    # Topic-fatigue: show the AI what we've covered recently so it can
    # downgrade repetitive stories.
    recent = get_recent_topics(days=3)
    recent_block = ""
    if recent:
        joined = "\n- ".join(t[:90] for t in recent[:25])
        recent_block = f"\n\n## УЖЕ ПУБЛИКОВАЛИ ЗА ПОСЛЕДНИЕ 3 ДНЯ\n- {joined}\n\nЕсли эта новость — про ту же тему (то же событие, та же забастовка, та же цена на бензин), снизь score на 1 или 2. Повторы аудиторию утомляют."

    # Canary Islands bonus: many of our readers are on the islands.
    canarias_boost = ""
    if "canari" in article.get("category", "").lower() or any(
        word in (article.get("title", "") + content).lower()
        for word in ["canarias", "tenerife", "gran canaria", "lanzarote",
                     "fuerteventura", "la palma", "las palmas", "canario"]
    ):
        canarias_boost = "\n\n🏝 ВАЖНО: Эта новость про Канары. Многие наши читатели живут на островах — повысь score на 1 (если фактов достаточно)."

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

❗ ОБЯЗАТЕЛЬНАЯ ПРОВЕРКА — ЕСТЬ ЛИ КОНКРЕТИКА:
Прежде чем ставить score ≥3, проверь — есть ли в статье хотя бы 2 из:
- Конкретные суммы (€X, Y%)
- Конкретные даты/дедлайны (с 1 апреля, до 30 июня 2026)
- Названия документов/форм (modelo 100, NIE, empadronamiento, IRPF)
- Названия ведомств (Hacienda, Seguridad Social, Extranjería)
- Конкретные регионы/города
Если фактов НЕТ — max score 2 → SKIP.
Повествовательная новость без цифр ≠ полезная новость.

5 — СРОЧНО: закон вступает в силу СЕГОДНЯ/ЗАВТРА, ЧП, эвакуация, визовые изменения с датой
4 — ВАЖНО: новые цены/штрафы/пошлины с конкретной датой и суммой, забастовки с датой и маршрутом, крупные изменения правил с дедлайном
3 — ИНТЕРЕСНО: культурные события с программой/датой, тренды с цифрами, инфраструктура с адресом/датой, необычные факты с проверяемой фактологией
2 — СЛАБО: корпоративная отчётность, абстрактная политика, тренды без цифр, биржевые колебания, спорт, криминальная хроника, повторы
1 — МУСОР: реклама, не про Испанию, пресс-релизы, мнения без фактов, жёлтая пресса

⚠️ ВАЖНО — НЕ ПУБЛИКОВАТЬ:
- Криминальную хронику (убийства, изнасилования, ограбления) — если это не массовое ЧП
- Жёлтую прессу (скандалы, сплетни, знаменитости)
- Корриду, бои быков
- Военные новости без прямого влияния на жизнь в Испании
- Статьи где весь "факт" — это одно общее заявление ("цены растут", "рынок охлаждается")

ПРИМЕРЫ:
✅ 5: "Новый закон аренды с 1 апреля: потолок +2%, штраф до €6000" → FULL
✅ 4: "10 апреля — забастовка в 12 аэропортах, задержка до 4 часов" → FULL
✅ 3: "В Валенсии 5 налоговых вычетов: за аренду €204, за детей €270" → SHORT
❌ 2: "Рост ВВП замедлился на 0.1%" → SKIP (нет практики)
❌ 2: "Меняется регулирование, рынок охлаждается" → SKIP (нет конкретики)
❌ 2: "Бывший матадор погиб от быка" → SKIP (жёлтая пресса)
❌ 1: "Philip Morris открыл офис в Кремниевой долине" → SKIP{recent_block}{canarias_boost}
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

## ПРАВИЛА ДЛЯ ЗАГОЛОВКА (для SHORT и FULL)
❌ ЗАПРЕЩЕНО:
- Шаблоны "Важные изменения в X", "Полезные новости про Y", "Что нужно знать о Z"
- Абстрактные слова: "изменения", "новости", "ситуация" без конкретики
- Начинать с "Снижение/Повышение/Изменение X" без цифр

✅ ТРЕБУЕТСЯ:
- Конкретика или интрига: цифра, название, действие, следствие
- Плохо: "Налоговые вычеты в Валенсии"
- Хорошо: "Валенсия: 5 вычетов до €700, дедлайн 30 июня"
- Плохо: "Изменения на границе ЕС"
- Хорошо: "Новая система EES в аэропортах сбоит — готовься к 2 часам в очереди"

## ФОРМАТ ТЕКСТА — БЕЗ ИСТОЧНИКА И ХЭШТЕГА
Источник и хэштег добавит система автоматически в конце. Твой текст НЕ должен содержать:
- Строку "Источник: ..."
- Строку "👇 Полный разбор — в комментарии"
- Строки с хэштегами #...
Просто заголовок + суть + (для SHORT) буллеты.

### Если SHORT:
POST:
[эмодзи, сильный уникальный] Конкретный цепляющий заголовок

1–2 предложения сути с ФАКТАМИ (сумма, дата, название).

Почему это важно:
• конкретный факт с цифрой/датой/документом
• ещё один конкретный факт

### Если FULL:
POST:
[эмодзи, сильный уникальный] Конкретный цепляющий заголовок

2–3 предложения сути — что произошло + главные цифры/даты.

COMMENT:
📰 Что произошло
(Расскажи новость полностью, не повторяя текст поста. Раскрой ВСЕ детали из статьи: цифры, даты, имена, названия документов, ведомств, регионов, сумм. 5–7 предложений. Читатель должен ЗНАТЬ всё из комментария без перехода на источник.)

🔍 Почему это важно
(Контекст: почему сейчас, что было до, какую проблему решают. 3–4 предложения.)

🏠 Как это касается тебя
• конкретное последствие (не "это может повлиять", а "ты будешь платить €X больше", "тебе нужно подать forma Y до даты Z")
• ещё одно конкретное последствие
• ещё одно
(Минимум 3 пункта. КАЖДЫЙ с конкретным фактом: сумма, действие, срок, документ.)

✅ Что делать
(1–3 конкретных шага: куда идти, что подать, до какой даты, какая форма. Если новость информационная — один совет "держать в уме для X".)

📌 Итог одной фразой
(Одно предложение — главный вывод.)
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
Содержание: {content}{image_note}

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

        # Strip any leftover "Источник:..." / "👇 Полный разбор..." / hashtag lines
        # that the model may have added despite instructions.
        post_text = re.sub(r"^\s*Источник:.*$", "", post_text, flags=re.MULTILINE)
        post_text = re.sub(r"^\s*👇.*$", "", post_text, flags=re.MULTILINE)
        post_text = re.sub(r"^\s*#[\wа-яА-ЯёЁ]+\s*$", "", post_text, flags=re.MULTILINE)
        post_text = re.sub(r"\n{3,}", "\n\n", post_text).strip()

        # Append unified footer: source + "read more" for FULL + hashtag.
        hashtag = _category_to_hashtag(category)
        footer_parts = [f"📎 [{article['source']}]({article['url']})"]
        if decision == "FULL":
            footer_parts.append("👇 Полный разбор — в комментариях")
        if hashtag:
            footer_parts.append(hashtag)
        post_text = post_text + "\n\n" + "\n".join(footer_parts)

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
