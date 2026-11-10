"""
nl2sql.py — the core: natural language -> SQL -> execute -> explain.

Design decisions worth being able to explain in an interview:
  1. The LLM never touches the database directly. It only *proposes* SQL text.
  2. Every proposed query passes a read-only guardrail BEFORE execution,
     and the database connection used to run it is opened read-only.
  3. The generated SQL is returned to the UI for transparency (no black box).
  4. Results are summarized by the LLM in plain English, grounded in the rows.
"""
import re
import sqlite3
from pathlib import Path
from llm import call_llm

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "operations.db"

# ----- guardrail -----
FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|PRAGMA|VACUUM)\b",
    re.IGNORECASE,
)


def is_safe(sql: str) -> tuple[bool, str]:
    """Allow only a single read-only SELECT. Returns (ok, reason)."""
    stripped = sql.strip().rstrip(";").strip()
    if ";" in stripped:
        return False, "Multiple statements are not allowed."
    if not stripped.lower().startswith(("select", "with")):
        return False, "Only SELECT queries are permitted."
    if FORBIDDEN.search(stripped):
        return False, "Query contains a forbidden (write/DDL) keyword."
    return True, "ok"


def get_schema() -> str:
    """Introspect the DB and return a compact schema string for the prompt."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    lines = []
    for t in tables:
        cols = cur.execute(f"PRAGMA table_info({t})").fetchall()
        col_str = ", ".join(f"{c[1]} {c[2]}" for c in cols)
        lines.append(f"{t}({col_str})")
        # For text columns with only a few distinct values (like status),
        # list the exact values so the model doesn't guess the spelling or case.
        for c in cols:
            if c[2].upper() != "TEXT":
                continue
            values = [r[0] for r in cur.execute(
                f"SELECT DISTINCT {c[1]} FROM {t} LIMIT 11").fetchall()]
            if len(values) <= 10:
                lines.append(f"  {t}.{c[1]} values: {', '.join(map(repr, values))}")
    con.close()
    return "\n".join(lines)


def generate_sql(question: str, schema: str) -> str:
    system = (
        "You translate questions into a single valid SQLite SELECT query. "
        "Return ONLY the SQL, no markdown, no explanation, no semicolon."
    )
    prompt = (
        f"Database schema:\n{schema}\n\n"
        f"Question: {question}\n\n"
        "Write one SQLite SELECT query that answers it. "
        "Use only tables/columns from the schema. Return SQL only."
    )
    raw = call_llm(prompt, system=system)
    # strip accidental markdown fences
    raw = re.sub(r"^```(?:sql)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    return raw


def run_query(sql: str):
    """Execute a validated SELECT. Returns (columns, rows).

    Second safety layer: the connection itself is opened read-only, so even a
    query that slipped past is_safe() could not change the data.
    """
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    con.close()
    return cols, rows


def explain_results(question: str, sql: str, cols, rows) -> str:
    preview = [dict(zip(cols, r)) for r in rows[:30]]
    system = "You explain query results to a non-technical manager, briefly and accurately."
    prompt = (
        f"Question: {question}\n"
        f"SQL used: {sql}\n"
        f"Result rows (up to 30 shown): {preview}\n\n"
        "In 2-4 sentences, answer the question in plain English using only these results. "
        "Do not invent numbers not present."
    )
    return call_llm(prompt, system=system)


def answer(question: str) -> dict:
    """Full pipeline. Returns a dict the UI can render."""
    schema = get_schema()
    sql = generate_sql(question, schema)
    ok, reason = is_safe(sql)
    if not ok:
        return {"sql": sql, "blocked": True, "reason": reason,
                "cols": None, "rows": None, "explanation": None}
    try:
        cols, rows = run_query(sql)
    except Exception as e:
        return {"sql": sql, "blocked": False, "error": str(e),
                "cols": None, "rows": None, "explanation": None}
    explanation = explain_results(question, sql, cols, rows)
    return {"sql": sql, "blocked": False, "cols": cols, "rows": rows,
            "explanation": explanation}


if __name__ == "__main__":
    # CLI smoke test:  python src/nl2sql.py "which category has the most backordered orders?"
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "which category has the most backordered orders?"
    out = answer(q)
    print("SQL:", out["sql"])
    if out.get("blocked"):
        print("BLOCKED:", out["reason"])
    elif out.get("error"):
        print("ERROR:", out["error"])
    else:
        print("ROWS:", out["rows"][:5])
        print("ANSWER:", out["explanation"])
