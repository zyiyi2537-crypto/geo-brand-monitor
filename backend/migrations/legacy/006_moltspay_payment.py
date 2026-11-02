"""Idempotent migration: add MoltsPay support fields to payment_sessions."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'geo_checker.db')


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    existing = {row[1] for row in cursor.execute("PRAGMA table_info(payment_sessions)")}

    if 'provider' not in existing:
        cursor.execute("ALTER TABLE payment_sessions ADD COLUMN provider TEXT NOT NULL DEFAULT 'stripe'")
    if 'chain' not in existing:
        cursor.execute("ALTER TABLE payment_sessions ADD COLUMN chain TEXT")
    if 'tx_hash' not in existing:
        cursor.execute("ALTER TABLE payment_sessions ADD COLUMN tx_hash TEXT")
    if 'wallet_address' not in existing:
        cursor.execute("ALTER TABLE payment_sessions ADD COLUMN wallet_address TEXT")

    conn.commit()
    conn.close()
    print("Migration 006 (MoltsPay payment fields) complete.")


if __name__ == '__main__':
    migrate()
