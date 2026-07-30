"""Create sales.db with sales_clients table and sample data."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "sales.db"

SAMPLE_DATA = [
    ("Alice Chen", "Acme Corp"),
    ("Alice Chen", "TechStart Inc"),
    ("Alice Chen", "Global Solutions"),
    ("Bob Martinez", "Retail Plus"),
    ("Bob Martinez", "Finance Hub"),
    ("Carol Johnson", "HealthCare Co"),
    ("Carol Johnson", "EduTech Ltd"),
]


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sales_person_name TEXT NOT NULL,
                associate_client_name TEXT NOT NULL
            )
        """)
        conn.execute("DELETE FROM sales_clients")
        conn.executemany(
            "INSERT INTO sales_clients (sales_person_name, associate_client_name) VALUES (?, ?)",
            SAMPLE_DATA,
        )
        conn.commit()
        print(f"Initialized {DB_PATH} with {len(SAMPLE_DATA)} rows")
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
