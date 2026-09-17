"""Database layer for TGFC Freight Desk.

Uses Postgres (Supabase) when DATABASE_URL is set in Streamlit secrets or the
environment; falls back to a local SQLite file for development. All queries
are written with %s placeholders and translated for SQLite.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

try:
    import streamlit as st
except Exception:  # pragma: no cover - allows import outside Streamlit
    st = None


def _database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if not url and st is not None:
        try:
            url = st.secrets.get("DATABASE_URL")
        except Exception:
            url = None
    return url


IS_PG = bool(_database_url())

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('sales','freight','admin')),
    password_hash TEXT NOT NULL,
    must_change BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS carriers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS requests (
    id SERIAL PRIMARY KEY,
    ref TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    requester_id INTEGER REFERENCES users(id),
    origin TEXT NOT NULL,
    dest TEXT NOT NULL,
    pallets INTEGER NOT NULL,
    lbs INTEGER NOT NULL,
    ship_date DATE NOT NULL,
    deliver_by DATE,
    temp TEXT NOT NULL,
    truck TEXT NOT NULL,
    product TEXT NOT NULL DEFAULT '',
    customer TEXT NOT NULL DEFAULT '',
    po TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    rfq_sent_at TIMESTAMPTZ,
    rfq_sent_by INTEGER REFERENCES users(id),
    rfq_reply_by TEXT NOT NULL DEFAULT '',
    rfq_message TEXT NOT NULL DEFAULT '',
    buy_rate NUMERIC,
    margin_pct NUMERIC,
    margin_amt NUMERIC,
    sell_rate NUMERIC,
    sell_carrier TEXT NOT NULL DEFAULT '',
    sell_transit TEXT NOT NULL DEFAULT '',
    sell_notes TEXT NOT NULL DEFAULT '',
    quoted_at TIMESTAMPTZ,
    quoted_by INTEGER REFERENCES users(id),
    booked_at TIMESTAMPTZ,
    decline_note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS rfq_carriers (
    id SERIAL PRIMARY KEY,
    request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    carrier_name TEXT NOT NULL,
    carrier_email TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS bids (
    id SERIAL PRIMARY KEY,
    request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    carrier_name TEXT NOT NULL,
    rate NUMERIC,
    transit TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    winner BOOLEAN NOT NULL DEFAULT FALSE,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

SCHEMA_SQLITE = (
    SCHEMA_PG.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
    .replace("TIMESTAMPTZ NOT NULL DEFAULT NOW()", "TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))")
    .replace("TIMESTAMPTZ", "TEXT")
    .replace("BOOLEAN NOT NULL DEFAULT TRUE", "INTEGER NOT NULL DEFAULT 1")
    .replace("BOOLEAN NOT NULL DEFAULT FALSE", "INTEGER NOT NULL DEFAULT 0")
    .replace("NUMERIC", "REAL")
    .replace("DATE NOT NULL", "TEXT NOT NULL")
    .replace("deliver_by DATE", "deliver_by TEXT")
)


def _connect():
    url = _database_url()
    if url:
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=10)
        conn.autocommit = True
        return conn
    path = os.environ.get("FREIGHT_DESK_SQLITE", "freight_desk.sqlite3")
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_conn = None


def conn():
    global _conn
    if _conn is None:
        _conn = _connect()
        init_schema(_conn)
    else:
        # make sure a dropped Postgres connection is re-opened
        try:
            if IS_PG and _conn.closed:
                _conn = _connect()
        except Exception:
            _conn = _connect()
    return _conn


def init_schema(c):
    schema = SCHEMA_PG if IS_PG else SCHEMA_SQLITE
    if IS_PG:
        with c.cursor() as cur:
            cur.execute(schema)
    else:
        c.executescript(schema)


def _q(sql: str) -> str:
    return sql if IS_PG else sql.replace("%s", "?")


def _fix_params(params):
    if IS_PG:
        return params
    # SQLite has no native booleans/dates; store as ints / ISO strings
    out = []
    for p in params:
        if isinstance(p, bool):
            out.append(1 if p else 0)
        elif hasattr(p, "isoformat"):
            out.append(p.isoformat())
        else:
            out.append(p)
    return tuple(out)


def run(sql: str, params=()):
    """Execute a write statement. Returns the new row id when RETURNING id is used."""
    c = conn()
    sql = _q(sql)
    params = _fix_params(params)
    try:
        if IS_PG:
            with c.cursor() as cur:
                cur.execute(sql, params)
                if cur.description:
                    row = cur.fetchone()
                    return row["id"] if row and "id" in row else row
                return None
        cur = c.execute(sql, params)
        if cur.description:
            row = cur.fetchone()
            return row["id"] if row and "id" in row.keys() else row
        return cur.lastrowid
    except Exception:
        if IS_PG:
            try:
                c.rollback()
            except Exception:
                pass
        raise


def fetchall(sql: str, params=()):
    c = conn()
    sql = _q(sql)
    params = _fix_params(params)
    if IS_PG:
        with c.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    cur = c.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def fetchone(sql: str, params=()):
    rows = fetchall(sql, params)
    return rows[0] if rows else None


def now():
    return datetime.now(timezone.utc)


def as_bool(v) -> bool:
    return bool(v) and v not in (0, "0", "false", "False")
