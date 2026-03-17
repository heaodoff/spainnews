"""Fetch and filter RSS feeds for relevant Spain news."""
import logging
from datetime import datetime, timedelta, timezone

import feedparser

from config import RSS_FEEDS, KEYWORDS
from database import is_published, is_duplicate_topic

logger = logging.getLogger(__name__)


def _is_relevant(title: str, summary: str) -> bool:
    """Check if article matches our keywords."""
    text = (title + " " + summary).lower()
    return any(kw.lower() in text for kw in KEYWORDS)


def fetch_articles(max_age_hours: int = 24) -> list[dict]:
    """
    Fetch articles from all RSS feeds.
    Returns a list of relevant, unpublished articles sorted by priority.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    articles = []

    for feed_config in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_config["url"])
            if feed.bozo and not feed.entries:
                logger.warning("Failed to parse feed: %s — %s", feed_config["name"], feed.bozo_exception)
                continue

            for entry in feed.entries[:20]:  # limit per feed
                url = entry.get("link", "")
                title = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()

                if not url or not title:
                    continue

                # Check publication date
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if published:
                    pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue

                # Skip already published
                if is_published(url):
                    continue

                # Skip duplicate topics (similar news already posted)
                if is_duplicate_topic(title):
                    logger.debug("Skipping duplicate topic: %s", title[:60])
                    continue

                # Check relevance
                if not _is_relevant(title, summary):
                    continue

                # Extract image URL from RSS entry
                image_url = ""
                # Try media:content / media:thumbnail
                media = entry.get("media_content", [])
                if media and isinstance(media, list):
                    image_url = media[0].get("url", "")
                if not image_url:
                    media_thumb = entry.get("media_thumbnail", [])
                    if media_thumb and isinstance(media_thumb, list):
                        image_url = media_thumb[0].get("url", "")
                # Try enclosures
                if not image_url:
                    enclosures = entry.get("enclosures", [])
                    for enc in enclosures:
                        if enc.get("type", "").startswith("image/"):
                            image_url = enc.get("href", enc.get("url", ""))
                            break
                # Try og:image from links
                if not image_url:
                    for link in entry.get("links", []):
                        if link.get("type", "").startswith("image/"):
                            image_url = link.get("href", "")
                            break

                articles.append({
                    "title": title,
                    "summary": summary[:2000],  # truncate long summaries
                    "url": url,
                    "source": feed_config["name"],
                    "category": feed_config["category"],
                    "priority": feed_config["priority"],
                    "image_url": image_url,
                })

        except Exception:
            logger.exception("Error fetching feed: %s", feed_config["name"])

    # Sort: priority 1 first, then by category diversity
    articles.sort(key=lambda a: a["priority"])
    logger.info("Fetched %d relevant articles from %d feeds", len(articles), len(RSS_FEEDS))
    return articles
