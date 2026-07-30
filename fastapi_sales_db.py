"""FastAPI service that exposes sales.db via POST endpoints."""
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn

DB_PATH = Path(__file__).parent / "sales.db"

app = FastAPI(
    title="Sales DB API",
    description="POST endpoints for querying and writing sales_clients in sales.db",
    version="1.0.0",
)


class ClientQueryRequest(BaseModel):
    sales_person_name: str = Field(..., min_length=1, examples=["Alice Chen"])


class ClientCreateRequest(BaseModel):
    sales_person_name: str = Field(..., min_length=1, examples=["Alice Chen"])
    associate_client_name: str = Field(..., min_length=1, examples=["Acme Corp"])


class ClientRecord(BaseModel):
    id: Optional[int] = None
    sales_person_name: str
    associate_client_name: str


def _get_connection() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Database not found: {DB_PATH}. Run init_sqlite_db.py first.",
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "db": str(DB_PATH), "db_exists": DB_PATH.exists()}


@app.post("/clients/query", response_model=list[ClientRecord])
def query_clients(body: ClientQueryRequest) -> list[ClientRecord]:
    """Return all clients associated with the given salesperson."""
    conn = _get_connection()
    try:
        cur = conn.execute(
            """
            SELECT id, sales_person_name, associate_client_name
            FROM sales_clients
            WHERE sales_person_name = ?
            """,
            (body.sales_person_name.strip(),),
        )
        rows = cur.fetchall()
        return [ClientRecord(**dict(r)) for r in rows]
    finally:
        conn.close()


@app.post("/clients", response_model=ClientRecord, status_code=201)
def create_client(body: ClientCreateRequest) -> ClientRecord:
    """Insert a new salesperson–client association into sales.db."""
    conn = _get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO sales_clients (sales_person_name, associate_client_name)
            VALUES (?, ?)
            """,
            (body.sales_person_name.strip(), body.associate_client_name.strip()),
        )
        conn.commit()
        return ClientRecord(
            id=cur.lastrowid,
            sales_person_name=body.sales_person_name.strip(),
            associate_client_name=body.associate_client_name.strip(),
        )
    finally:
        conn.close()


if __name__ == "__main__":
    uvicorn.run("fastapi_sales_db:app", host="0.0.0.0", port=8020, reload=False)
