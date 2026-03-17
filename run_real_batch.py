"""Fetch real articles from RSS and send top 5 for approval."""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])

from database import init_db, mark_published
from fetcher import fetch_articles
from translator import process_article, check_needs_approval
from bot import send_for_approval, post_to_channel

TARGET = 5


async def run():
    init_db()
    print(f"\n{'=' * 60}")
    print(f"БОЕВОЙ РЕЖИМ — реальные статьи из RSS, цель: {TARGET} постов")
    print(f"{'=' * 60}\n")

    articles = fetch_articles(max_age_hours=24)
    if not articles:
        print("Нет новых статей в RSS. Попробуй увеличить max_age_hours.")
        return

    print(f"Найдено {len(articles)} статей в RSS. Обрабатываю...\n")

    sent = 0
    checked = 0
    for article in articles:
        if sent >= TARGET:
            break
        if checked >= TARGET * 5:
            break
        checked += 1

        print(f"[{checked}] {article['title'][:70]}...")
        processed = process_article(article)
        if not processed:
            print("    → SKIP (AI отклонил)\n")
            continue

        print(f"    Score: {processed['score']} | Format: {processed['format']} | Cat: {processed['category']}")

        # All go through approval for admin review
        approval = check_needs_approval(article, processed)
        pid = await send_for_approval(processed, approval, urgent=False)
        print(f"    📤 Отправлено на согласование #{pid}")
        print(f"    Рек: {approval['recommendation']} | Услуга: {'ДА' if approval['suggest_service'] else 'НЕТ'}\n")

        sent += 1
        await asyncio.sleep(1)

    print(f"\n{'=' * 60}")
    print(f"Отправлено {sent} постов на согласование.")
    print("Нажми кнопки в Telegram для публикации.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(run())
