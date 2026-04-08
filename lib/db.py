"""PostgreSQL position tracking."""

import os
import psycopg2
from datetime import datetime, timezone

DB_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/claude_trader")


def get_conn():
    return psycopg2.connect(DB_URL)


def init_db():
    """Create tables if they don't exist."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            side VARCHAR(5) NOT NULL,
            entry_price DOUBLE PRECISION NOT NULL,
            quantity DOUBLE PRECISION NOT NULL,
            stop_loss DOUBLE PRECISION NOT NULL,
            target DOUBLE PRECISION,
            reason TEXT,
            status VARCHAR(10) DEFAULT 'open',
            entry_time TIMESTAMPTZ DEFAULT NOW(),
            exit_price DOUBLE PRECISION,
            exit_time TIMESTAMPTZ,
            pnl DOUBLE PRECISION,
            score INTEGER
        );

        CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            position_id INTEGER REFERENCES positions(id),
            symbol VARCHAR(20) NOT NULL,
            side VARCHAR(5) NOT NULL,
            entry_price DOUBLE PRECISION NOT NULL,
            exit_price DOUBLE PRECISION NOT NULL,
            quantity DOUBLE PRECISION NOT NULL,
            pnl DOUBLE PRECISION NOT NULL,
            pnl_pct DOUBLE PRECISION NOT NULL,
            reason_open TEXT,
            reason_close TEXT,
            entry_time TIMESTAMPTZ,
            exit_time TIMESTAMPTZ DEFAULT NOW(),
            duration_hours DOUBLE PRECISION
        );

        CREATE TABLE IF NOT EXISTS config (
            key VARCHAR(50) PRIMARY KEY,
            value TEXT NOT NULL
        );

        INSERT INTO config (key, value) VALUES
            ('capital', '2000'),
            ('risk_per_trade', '0.01'),
            ('max_positions', '5'),
            ('leverage', '3')
        ON CONFLICT (key) DO NOTHING;
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("DB initialized.")


def open_position(symbol, side, entry_price, stop_loss, target, quantity, reason, score=0):
    """Record a new position."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO positions (symbol, side, entry_price, quantity, stop_loss, target, reason, score)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (symbol, side, entry_price, quantity, stop_loss, target, reason, score))
    pos_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return pos_id


def close_position(pos_id, exit_price, reason):
    """Close a position and record the trade."""
    conn = get_conn()
    cur = conn.cursor()

    # Get position details
    cur.execute("SELECT * FROM positions WHERE id = %s AND status = 'open'", (pos_id,))
    pos = cur.fetchone()
    if not pos:
        cur.close()
        conn.close()
        return None

    # Calculate PnL
    symbol, side, entry, qty = pos[1], pos[2], pos[3], pos[4]
    if side == 'long':
        pnl = (exit_price - entry) * qty
    else:
        pnl = (entry - exit_price) * qty

    # Deduct commission
    commission = (entry * qty + exit_price * qty) * 0.00075
    pnl -= commission
    pnl_pct = pnl / (entry * qty) * 100

    entry_time = pos[10]
    duration = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600 if entry_time else 0

    # Update position
    cur.execute("""
        UPDATE positions SET status = 'closed', exit_price = %s, exit_time = NOW(), pnl = %s
        WHERE id = %s
    """, (exit_price, pnl, pos_id))

    # Record trade
    cur.execute("""
        INSERT INTO trades (position_id, symbol, side, entry_price, exit_price, quantity,
                           pnl, pnl_pct, reason_open, reason_close, entry_time, duration_hours)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (pos_id, symbol, side, entry, exit_price, qty, pnl, pnl_pct, pos[7], reason, entry_time, duration))

    conn.commit()
    cur.close()
    conn.close()
    return {"pnl": pnl, "pnl_pct": pnl_pct, "duration_hours": duration}


def get_open_positions():
    """Get all open positions."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, side, entry_price, quantity, stop_loss, target, reason,
               entry_time, score
        FROM positions WHERE status = 'open'
        ORDER BY entry_time
    """)
    positions = cur.fetchall()
    cur.close()
    conn.close()
    return positions


def get_stats():
    """Get trading statistics."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            count(*) as total_trades,
            count(*) FILTER (WHERE pnl > 0) as wins,
            count(*) FILTER (WHERE pnl <= 0) as losses,
            round(sum(pnl)::numeric, 2) as total_pnl,
            round(avg(pnl)::numeric, 2) as avg_pnl
        FROM trades
    """)
    stats = cur.fetchone()
    cur.close()
    conn.close()
    return stats


def get_config(key):
    """Get config value."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM config WHERE key = %s", (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None


if __name__ == "__main__":
    init_db()
