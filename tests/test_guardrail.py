"""
Unit tests for the read-only guardrail (no API key needed).

Run:  python -m pytest tests/     (or)     python tests/test_guardrail.py
"""
import sqlite3
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.modules.setdefault("llm", types.SimpleNamespace(call_llm=None))  # no LLM needed

from nl2sql import DB_PATH, is_safe, run_query  # noqa: E402

ALLOWED = [
    "SELECT * FROM orders",
    "select category, count(*) from products group by category",
    "WITH t AS (SELECT sku FROM inventory) SELECT * FROM t",
    "SELECT * FROM orders;",  # one trailing semicolon is fine
]

BLOCKED = [
    "DROP TABLE products",
    "DELETE FROM orders",
    "UPDATE inventory SET on_hand_qty = 0",
    "INSERT INTO orders VALUES (1, 'x', 'y', '2025-01-01', 1, 'Fulfilled')",
    "SELECT 1; DROP TABLE orders",
    "PRAGMA table_info(orders)",
    "ATTACH DATABASE 'other.db' AS other",
    "SELECT * FROM orders WHERE 1=1 UNION SELECT * FROM orders; DELETE FROM orders",
]


def test_allows_read_only_queries():
    for sql in ALLOWED:
        ok, reason = is_safe(sql)
        assert ok, f"should be allowed: {sql!r} ({reason})"


def test_blocks_writes_and_multiple_statements():
    for sql in BLOCKED:
        ok, _ = is_safe(sql)
        assert not ok, f"should be blocked: {sql!r}"


def test_connection_is_read_only():
    """Even if a write reached the database, the read-only connection refuses it."""
    if not DB_PATH.exists():
        import pytest
        pytest.skip("run python src/build_db.py first")
    try:
        run_query("DELETE FROM orders")
    except sqlite3.OperationalError as e:
        assert "readonly" in str(e).lower()
    else:
        raise AssertionError("write succeeded on a read-only connection")


if __name__ == "__main__":
    test_allows_read_only_queries()
    test_blocks_writes_and_multiple_statements()
    if DB_PATH.exists():
        test_connection_is_read_only()
    print("All guardrail tests passed.")
