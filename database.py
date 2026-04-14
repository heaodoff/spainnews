"""SQLite database for tracking published articles."""
import sqlite3
from config import DB_PATH


def init_db():
    """Create tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS published (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            title TEXT,
            title_normalized TEXT,
            source TEXT,
            published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Add title_normalized column if missing (migration for existing DB)
    try:
        conn.execute("ALTER TABLE published ADD COLUMN title_normalized TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()
    conn.close()


def is_published(url: str) -> bool:
    """Check if an article URL was already published."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT 1 FROM published WHERE url = ?", (url,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def is_duplicate_topic(title: str) -> bool:
    """Check if a similar topic was already published (fuzzy match on normalized title).

    Uses two checks:
    1. Word overlap on normalized title (>50% = duplicate)
    2. Key entity overlap — proper nouns, numbers, names (>60% = duplicate)
    This catches the same story reported by different sources with different wording.
    """
    normalized = _normalize_title(title)
    entities = _extract_entities(title)
    if not normalized:
        return False
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT title, title_normalized FROM published ORDER BY id DESC LIMIT 300")
    rows = cur.fetchall()
    conn.close()

    words_new = set(normalized.split())

    for (prev_title, prev_norm) in rows:
        if not prev_norm:
            continue
        words_old = set(prev_norm.split())
        if not words_new or not words_old:
            continue

        # Check 1: word overlap
        overlap = len(words_new & words_old)
        smaller = min(len(words_new), len(words_old))
        if smaller > 0 and overlap / smaller > 0.5:
            return True

        # Check 2: entity overlap (names, numbers, orgs)
        if entities and prev_title:
            prev_entities = _extract_entities(prev_title)
            if prev_entities:
                ent_overlap = len(entities & prev_entities)
                ent_smaller = min(len(entities), len(prev_entities))
                if ent_smaller > 0 and ent_overlap / ent_smaller > 0.6 and ent_overlap >= 2:
                    return True

    return False


def _normalize_title(title: str) -> str:
    """Normalize title for comparison: lowercase, remove short words and punctuation."""
    import re
    text = re.sub(r'[^\w\s]', '', title.lower())
    # Remove common stopwords in Spanish and English
    stopwords = {
        'para', 'como', 'esta', 'este', 'esto', 'que', 'del', 'los', 'las',
        'una', 'uno', 'por', 'con', 'son', 'sus', 'más', 'pero', 'sobre',
        'entre', 'desde', 'hasta', 'tras', 'ante', 'bajo', 'según', 'hacia',
        'the', 'and', 'for', 'with', 'from', 'that', 'this', 'are', 'has',
        'have', 'will', 'been', 'could', 'would', 'should', 'into', 'about',
        'new', 'its', 'all', 'also', 'than', 'they', 'their', 'what', 'when',
    }
    words = [w for w in text.split() if len(w) > 2 and w not in stopwords]
    return ' '.join(words)


def _extract_entities(title: str) -> set:
    """Extract key entities from title: capitalized words, numbers, acronyms."""
    import re
    entities = set()
    # Capitalized words (proper nouns, names, organizations)
    for word in re.findall(r'\b[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]{2,}\b', title):
        entities.add(word.lower())
    # Acronyms (2+ uppercase letters)
    for word in re.findall(r'\b[A-ZÁÉÍÓÚÑÜ]{2,}\b', title):
        entities.add(word.lower())
    # Numbers with context (percentages, amounts)
    for num in re.findall(r'\d+[.,]?\d*\s*%?', title):
        entities.add(num.strip())
    return entities


def mark_published(url: str, title: str, source: str):
    """Mark an article as published."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR IGNORE INTO published (url, title, title_normalized, source) VALUES (?, ?, ?, ?)",
        (url, title, _normalize_title(title), source),
    )
    conn.commit()
    conn.close()


def get_published_count() -> int:
    """Return total number of published articles."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT COUNT(*) FROM published")
    count = cur.fetchone()[0]
    conn.close()
    return count


def get_recent_topics(days: int = 3) -> list[str]:
    """Return titles of articles published in the last N days.

    Used for topic-fatigue detection: if a new candidate covers the
    same ground as something published recently, its score gets reduced.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT title FROM published WHERE published_at >= datetime('now', ?) ORDER BY id DESC LIMIT 40",
        (f"-{days} days",),
    )
    titles = [row[0] for row in cur.fetchall()]
    conn.close()
    return titles


# ── Pending posts (approval queue) ──

def _init_pending():
    """Create pending_posts table if needed."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_url TEXT NOT NULL,
            article_title TEXT,
            article_source TEXT,
            post_data TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def save_pending(article_url: str, article_title: str, article_source: str, post_data_json: str) -> int:
    """Save a post awaiting approval. Returns the pending ID."""
    _init_pending()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "INSERT INTO pending_posts (article_url, article_title, article_source, post_data) VALUES (?, ?, ?, ?)",
        (article_url, article_title, article_source, post_data_json),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_pending(pid: int) -> dict | None:
    """Get a pending post by ID."""
    _init_pending()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT id, article_url, article_title, article_source, post_data, status FROM pending_posts WHERE id = ?", (pid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "url": row[1], "title": row[2], "source": row[3], "post_data": row[4], "status": row[5]}


def update_pending_status(pid: int, status: str):
    """Update pending post status (approved/rejected/published)."""
    _init_pending()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE pending_posts SET status = ? WHERE id = ?", (status, pid))
    conn.commit()
    conn.close()
