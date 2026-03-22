"""Main entry point — scheduler + callback handler for Spain News Bot."""
import asyncio
import json
import logging
import sys
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import SCHEDULE_HOURS, TIMEZONE, MAX_ARTICLES_PER_RUN, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID
from database import init_db, mark_published, get_published_count
from fetcher import fetch_articles
from translator import process_article, is_urgent, check_needs_approval
from bot import post_to_channel, send_for_approval, handle_approval_callback, bot
from viral_gen import generate_viral_post

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


async def run_cycle():
    """One publish cycle: fetch → translate → check approval → post or queue."""
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz).strftime("%H:%M %d.%m.%Y")
    logger.info("=== Starting publish cycle at %s ===", now)

    articles = fetch_articles(max_age_hours=8)
    if not articles:
        logger.info("No new relevant articles found")
        return

    logger.info("Found %d candidate articles", len(articles))

    posted = 0
    queued = 0
    checked = 0
    for article in articles:
        if posted + queued >= MAX_ARTICLES_PER_RUN:
            break
        if checked >= MAX_ARTICLES_PER_RUN * 5:
            break
        checked += 1

        processed = process_article(article)
        if not processed:
            continue

        # Check if this post needs admin approval
        approval = check_needs_approval(article, processed)

        if approval["needs_approval"]:
            # Send to admin for approval — don't publish yet
            await send_for_approval(processed, approval, urgent=False)
            queued += 1
            logger.info("Queued for approval: %s", article["title"][:60])
        else:
            # Ordinary news — publish automatically
            success = await post_to_channel(processed)
            if success:
                mark_published(article["url"], article["title"], article["source"])
                posted += 1
                await asyncio.sleep(3)

    logger.info("Published %d, queued %d for approval. Total in DB: %d",
                posted, queued, get_published_count())


async def run_urgent_check():
    """Check for breaking news every 15 minutes — queue important, post rest."""
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz).strftime("%H:%M")
    logger.info("--- Urgent check at %s ---", now)

    articles = fetch_articles(max_age_hours=2)
    if not articles:
        return

    urgent_posted = 0
    checked = 0
    for article in articles:
        if urgent_posted >= 2:
            break
        if checked >= 10:
            break
        checked += 1

        if not is_urgent(article):
            continue

        processed = process_article(article)
        if not processed:
            continue

        # Urgent news also check for approval
        approval = check_needs_approval(article, processed)

        if approval["needs_approval"]:
            await send_for_approval(processed, approval, urgent=True)
            logger.info("🚨 URGENT queued for approval: %s", article["title"][:70])
        else:
            success = await post_to_channel(processed, urgent=True)
            if success:
                mark_published(article["url"], article["title"], article["source"])
                logger.info("🚨 URGENT posted: %s", article["title"][:70])

        urgent_posted += 1
        await asyncio.sleep(2)


async def run_viral_post():
    """Generate and queue a viral/useful post for approval."""
    logger.info("--- Generating viral post ---")
    try:
        processed = generate_viral_post()
        if not processed:
            logger.warning("Failed to generate viral post")
            return

        # Always send through approval
        approval_info = {
            "needs_approval": True,
            "reason": "Вирусный/полезный пост (не новость)",
            "recommendation": "Полезный контент для роста подписчиков",
            "suggest_service": False,
            "service_reason": "",
            "cta_text": "",
        }
        await send_for_approval(processed, approval_info, urgent=False)
        logger.info("Viral post queued for approval: %s", processed["title"][:60])
    except Exception:
        logger.exception("Error in viral post generation")


async def poll_callbacks():
    """Poll for admin callback button presses (approve/reject)."""
    offset = None
    while True:
        try:
            updates = await bot.get_updates(
                offset=offset,
                timeout=10,
                allowed_updates=["callback_query", "message"],
            )
            for update in updates:
                offset = update.update_id + 1

                cq = update.callback_query
                if not cq:
                    continue
                # Only handle callbacks from admin
                if cq.from_user.id != ADMIN_CHAT_ID:
                    await bot.answer_callback_query(cq.id, text="⛔ Нет доступа")
                    continue
                data = cq.data or ""
                if data.startswith("approve:") or data.startswith("reject:"):
                    await handle_approval_callback(data, cq.id)
        except Exception:
            logger.exception("Error in callback polling")
            await asyncio.sleep(5)


async def main():
    """Start the scheduler + callback poller."""
    init_db()
    logger.info("Spain News Bot started!")
    logger.info("Schedule: posting at %s (Madrid time)", SCHEDULE_HOURS)
    logger.info("Admin approval chat: %s", ADMIN_CHAT_ID)

    scheduler = AsyncIOScheduler(
        timezone=TIMEZONE,
        job_defaults={
            "misfire_grace_time": 600,  # 10 min — don't skip if slightly late
            "coalesce": True,           # merge missed runs into one
        },
    )

    for hour in SCHEDULE_HOURS:
        scheduler.add_job(
            run_cycle,
            CronTrigger(hour=hour, minute=0, timezone=TIMEZONE),
            id=f"publish_{hour}",
            name=f"Publish at {hour}:00",
        )

    scheduler.add_job(
        run_urgent_check,
        "interval",
        minutes=15,
        id="urgent_check",
        name="Urgent news check",
    )

    # Viral/useful post — once a day at 11:00
    scheduler.add_job(
        run_viral_post,
        CronTrigger(hour=11, minute=0, timezone=TIMEZONE),
        id="viral_post",
        name="Viral post at 11:00",
    )

    scheduler.start()
    logger.info("Scheduler started. Callback poller running. Waiting...")

    # Run immediate cycle if requested
    if "--now" in sys.argv:
        logger.info("Running immediate cycle (--now flag)")
        await run_cycle()

    # Run callback poller (handles admin button presses)
    # This replaces the old sleep loop — it polls for updates AND keeps the process alive
    try:
        await poll_callbacks()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
