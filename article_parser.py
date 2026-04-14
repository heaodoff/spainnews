"""Fetch and extract full article text from a URL.

Strategy:
1. Fetch HTML with a browser User-Agent.
2. Try common article containers (article, main, .entry-content, etc.).
3. Fallback: take all <p> inside <body>.
4. Clean up: strip scripts, styles, nav, footer.
Returns a plain text string (first ~5000 chars) or empty string on failure.
"""
import logging

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Selectors ordered by preference
ARTICLE_SELECTORS = [
    "article",
    '[itemprop="articleBody"]',
    ".article-body",
    ".article-content",
    ".entry-content",
    ".post-content",
    ".story-body",
    ".c-content",
    ".news-body",
    "main",
]

STRIP_TAGS = ["script", "style", "nav", "header", "footer", "aside",
              "form", "noscript", "iframe", "svg", ".advertisement",
              ".related", ".share", ".comments", ".newsletter"]


def fetch_article_text(url: str, timeout: int = 12) -> str:
    """Download URL and extract article body text. Returns empty string on failure."""
    if not url or not url.startswith("http"):
        return ""

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": UA}) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                logger.debug("Article fetch %s → HTTP %d", url[:80], resp.status_code)
                return ""
            html = resp.text
    except Exception as e:
        logger.debug("Article fetch failed %s: %s", url[:80], e)
        return ""

    try:
        soup = BeautifulSoup(html, "lxml")

        # Remove junk tags
        for tag in soup.find_all(["script", "style", "nav", "header",
                                  "footer", "aside", "form", "noscript",
                                  "iframe", "svg"]):
            tag.decompose()

        # Try preferred selectors
        body = None
        for sel in ARTICLE_SELECTORS:
            found = soup.select_one(sel)
            if found:
                body = found
                break

        if body is None:
            body = soup.find("body") or soup

        # Extract paragraphs
        paragraphs = []
        for p in body.find_all(["p", "h2", "h3", "li"]):
            txt = p.get_text(" ", strip=True)
            if len(txt) >= 25:  # skip tiny fragments
                paragraphs.append(txt)

        text = "\n".join(paragraphs)

        # Truncate to keep API calls cheap
        if len(text) > 5000:
            text = text[:5000].rsplit(" ", 1)[0] + "..."

        return text
    except Exception:
        logger.exception("Failed to parse article %s", url[:80])
        return ""
