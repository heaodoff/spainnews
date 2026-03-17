"""Telegram bot — post to channel, comment in discussion group, approval flow."""
import json
import logging
import asyncio
import os

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL, ADMIN_CHAT_ID, STRIPE_LINK
from image_gen import generate_news_image
from database import save_pending, get_pending, update_pending_status, mark_published

logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Cache for discussion group ID
_discussion_chat_id: int | None = None


async def _get_discussion_chat_id() -> int | None:
    """Get the linked discussion group ID (cached)."""
    global _discussion_chat_id
    if _discussion_chat_id is None:
        try:
            chat = await bot.get_chat(TELEGRAM_CHANNEL)
            _discussion_chat_id = chat.linked_chat_id
            if _discussion_chat_id:
                logger.info("Discussion group ID: %s", _discussion_chat_id)
            else:
                logger.warning("No discussion group linked to channel")
        except Exception:
            logger.exception("Failed to get discussion group ID")
    return _discussion_chat_id


async def post_to_channel(processed: dict, urgent: bool = False) -> bool:
    """
    Post short version to channel, then add detailed comment in discussion group.
    Falls back to channel reply if discussion group is unavailable.
    """
    try:
        text = processed["short_post"]
        if urgent:
            # BREAKING format
            text = "🚨 СРОЧНО: " + text

        # Generate branded image (DALL-E background + Pillow text overlay)
        image_headline = processed.get("image_headline", processed["title"])
        category = processed.get("category", "Новости")
        source = processed.get("source", "")
        image_prompt = processed.get("image_description", "")
        image_path = generate_news_image(
            headline=image_headline,
            category=category,
            source=source,
            urgent=urgent,
            image_prompt=image_prompt,
        )

        # Send photo with caption to channel (or text fallback)
        # Telegram caption limit is 1024 chars
        caption = text if len(text) <= 1024 else text[:1020] + "..."

        # Add Stripe button if service mode
        reply_markup = None
        if processed.get("add_service_button"):
            btn_text = processed.get("service_button_text", "📋 Узнать как сделать самому")
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(btn_text, url=STRIPE_LINK)]
            ])

        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as photo:
                message = await bot.send_photo(
                    chat_id=TELEGRAM_CHANNEL,
                    photo=photo,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )
            # Clean up image file
            try:
                os.remove(image_path)
            except OSError:
                pass
        else:
            message = await bot.send_message(
                chat_id=TELEGRAM_CHANNEL,
                text=text,
                disable_web_page_preview=False,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
            )

        # Only post comment for FULL format (not SHORT)
        post_format = processed.get("format", "FULL")
        detailed = processed.get("detailed_comment")

        if post_format == "FULL" and detailed:
            # Wait for Telegram to auto-forward to discussion group
            await asyncio.sleep(4)

            discussion_id = await _get_discussion_chat_id()

            if discussion_id:
                try:
                    # Find the auto-forwarded message in discussion group
                    fwd_msg_id = None
                    updates = await bot.get_updates(timeout=5, allowed_updates=[])
                    max_uid = None
                    for upd in updates:
                        max_uid = upd.update_id
                        m = upd.message
                        if m and m.chat_id == discussion_id and getattr(m, 'is_automatic_forward', False):
                            fwd_msg_id = m.message_id
                            logger.info("Found auto-forwarded msg %d in discussion group", fwd_msg_id)
                    if max_uid is not None:
                        await bot.get_updates(offset=max_uid + 1, timeout=1, allowed_updates=[])

                    if fwd_msg_id:
                        await bot.send_message(
                            chat_id=discussion_id,
                            text=f"📋 *Подробный разбор:*\n\n{detailed}",
                            reply_to_message_id=fwd_msg_id,
                            parse_mode=ParseMode.MARKDOWN,
                        )
                        logger.info("Comment posted as reply to forwarded msg %d", fwd_msg_id)
                    else:
                        logger.warning("Auto-forwarded msg not found, posting standalone")
                        await bot.send_message(
                            chat_id=discussion_id,
                            text=f"📋 *Подробный разбор:*\n\n{detailed}",
                            parse_mode=ParseMode.MARKDOWN,
                        )
                except Exception:
                    logger.exception("Failed to comment in discussion group")
        else:
            logger.info("SHORT format — no comment needed")

        logger.info("Posted: %s", processed["title"])
        return True

    except Exception:
        logger.exception("Error posting to Telegram: %s", processed["title"])
        return False


async def send_for_approval(processed: dict, approval_info: dict, urgent: bool = False) -> int:
    """
    Send a post for admin approval. Returns the pending post ID.
    """
    post_data = json.dumps({
        "processed": processed,
        "urgent": urgent,
        "approval_info": approval_info,
    }, ensure_ascii=False)

    pid = save_pending(
        article_url=processed.get("url", ""),
        article_title=processed.get("title", ""),
        article_source=processed.get("source", ""),
        post_data_json=post_data,
    )

    # Build approval message
    headline = processed.get("title", "")[:100]
    rec = approval_info.get("recommendation", "?")
    reason = approval_info.get("reason", "")
    svc_reason = approval_info.get("service_reason", "")
    cta = approval_info.get("cta_text", "")
    suggest_svc = approval_info.get("suggest_service", False)

    msg = (
        f"📋 *СОГЛАСОВАНИЕ ПОСТА* \\#{pid}\n\n"
        f"*Заголовок:* {headline}\n\n"
        f"*Почему важная:*\n• {reason}\n\n"
        f"*Рекомендация:* {rec}\n\n"
        f"*Добавить услугу:* {'✅ ДА' if suggest_svc else '❌ НЕТ'}\n"
        f"{'*Почему:* ' + svc_reason if svc_reason else ''}\n"
        f"{'*CTA:* ' + cta if cta else ''}\n\n"
        f"{'🚨 СРОЧНАЯ НОВОСТЬ' if urgent else ''}"
    )

    # Inline keyboard with 4 options
    keyboard = [
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:{pid}:plain"),
            InlineKeyboardButton("✅ + Услуга", callback_data=f"approve:{pid}:service"),
        ],
        [
            InlineKeyboardButton("✏️ Без услуги", callback_data=f"approve:{pid}:no_service"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject:{pid}"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
        )
        logger.info("Sent for approval: #%d — %s", pid, headline[:50])
    except Exception:
        logger.exception("Failed to send approval request")

    return pid


async def handle_approval_callback(callback_data: str, callback_query_id: str) -> bool:
    """
    Handle admin's approval/rejection button press.
    callback_data format: "approve:{pid}:plain|service|no_service" or "reject:{pid}"
    Returns True if a post was published.
    """
    parts = callback_data.split(":")
    action = parts[0]
    pid = int(parts[1])

    pending = get_pending(pid)
    if not pending or pending["status"] != "pending":
        await bot.answer_callback_query(callback_query_id, text="Этот пост уже обработан")
        return False

    if action == "reject":
        update_pending_status(pid, "rejected")
        try:
            await bot.answer_callback_query(callback_query_id, text="❌ Пост отклонён")
        except Exception:
            pass
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"❌ Пост #{pid} отклонён")
        return False

    # action == "approve"
    mode = parts[2] if len(parts) > 2 else "plain"

    data = json.loads(pending["post_data"])
    processed = data["processed"]
    urgent = data.get("urgent", False)
    approval_info = data.get("approval_info", {})

    # Add CTA to the post if mode == "service"
    if mode == "service":
        cta = approval_info.get("cta_text", "")
        if not cta:
            cta = "Нужна помощь с оформлением? Я расскажу как сделать всё самому — пошагово и без ошибок"
        processed["short_post"] += f"\n\n💡 {cta}"
        # Inline button on the main post
        processed["add_service_button"] = True
        processed["service_button_text"] = "📋 Узнать как сделать самому"
        # Add CTA link in comment too
        if processed.get("detailed_comment"):
            processed["detailed_comment"] += (
                f"\n\n━━━━━━━━━━━━━━\n"
                f"💡 *{cta}*\n"
                f"👉 [Узнать подробнее]({STRIPE_LINK})"
            )

    update_pending_status(pid, "approved")
    success = await post_to_channel(processed, urgent=urgent)

    if success:
        mark_published(pending["url"], pending["title"], pending["source"])
        update_pending_status(pid, "published")
        svc_label = " + услуга" if mode == "service" else ""
        try:
            await bot.answer_callback_query(callback_query_id, text=f"✅ Опубликовано{svc_label}!")
        except Exception:
            pass  # callback may have expired
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"✅ Пост #{pid} опубликован{svc_label}")
        return True
    else:
        try:
            await bot.answer_callback_query(callback_query_id, text="⚠️ Ошибка публикации")
        except Exception:
            pass
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"⚠️ Ошибка публикации поста #{pid}")
        return False


async def send_status(text: str):
    """Send a status/diagnostic message to the channel."""
    try:
        await bot.send_message(chat_id=TELEGRAM_CHANNEL, text=text)
    except Exception:
        logger.exception("Error sending status message")
