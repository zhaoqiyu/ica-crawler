import sqlite3
from datetime import datetime, timezone
from typing import Dict, Optional

# Fixed metadata columns — keys as seen in the CONTENTdm API across known collections.
# Any field key not in this set is silently ignored.
METADATA_COLUMNS = [
    "title",    # Title
    "titlea",   # Title Larger Entity
    "collec",   # Collection
    "creato",   # Artist / Creator
    "date",     # Date
    "descri",   # Description
    "identi",   # ID Number Current Repository
    "langua",   # Location Current Repository
    "subjec",   # Subject / Inscription
    "format",   # Measurements
    "source",   # Source
    "type",     # Work Type
    "contri",   # Support (IWM)
    "medium",   # Medium (IWM)
    "stylep",   # Style/Period (IWM)
    "rights",   # Rights
]

_meta_cols_sql = "\n".join(f"    {col:<10} TEXT," for col in METADATA_COLUMNS)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    collection  TEXT    NOT NULL,
    item_id     INTEGER NOT NULL,
{_meta_cols_sql}
    image_url   TEXT,
    image_path  TEXT,
    crawled_at  TEXT,
    UNIQUE(collection, item_id)
);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def item_exists(conn: sqlite3.Connection, collection: str, item_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM items WHERE collection = ? AND item_id = ?",
        (collection, item_id),
    ).fetchone()
    return row is not None


def upsert_item(
    conn: sqlite3.Connection,
    collection: str,
    item_id: int,
    metadata: Dict[str, Optional[str]],
    image_url: Optional[str],
    image_path: Optional[str],
) -> None:
    known = {k: metadata.get(k) for k in METADATA_COLUMNS}

    cols = ["collection", "item_id"] + METADATA_COLUMNS + ["image_url", "image_path", "crawled_at"]
    vals = (
        [collection, item_id]
        + [known[k] for k in METADATA_COLUMNS]
        + [image_url, image_path, datetime.now(timezone.utc).isoformat()]
    )
    placeholders = ", ".join(["?"] * len(vals))
    updates = ", ".join(f"{c} = excluded.{c}" for c in METADATA_COLUMNS + ["image_url", "image_path", "crawled_at"])

    conn.execute(
        f"""
        INSERT INTO items ({', '.join(cols)})
        VALUES ({placeholders})
        ON CONFLICT(collection, item_id) DO UPDATE SET {updates}
        """,
        vals,
    )
    conn.commit()
