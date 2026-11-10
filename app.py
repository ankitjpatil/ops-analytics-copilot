"""
app.py — Ops Analytics Copilot (Streamlit UI)

Run:  python -m streamlit run app.py
Ask questions in plain English; see the answer, a chart, the result table,
and the generated SQL (transparency).
"""
import sqlite3
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent / "src"))

import altair as alt
import pandas as pd
import streamlit as st

from nl2sql import DB_PATH, answer, get_schema

st.set_page_config(page_title="Ops Analytics Copilot", page_icon="📊", layout="wide")

EXAMPLES = [
    "Which category has the most backordered orders?",
    "Total order quantity by warehouse",
    "Total quantity ordered per month in 2025",
    "Share of orders by status",
    "Which SKUs are below their reorder point at Barrie-DC?",
    "Top 5 SKUs by total ordered quantity",
]

if not DB_PATH.exists():
    st.error("Database not found. Run `python src/build_db.py` first.")
    st.stop()


# ---------- helpers ----------
@st.cache_data
def kpis() -> dict:
    """Headline numbers, read straight from the database (read-only)."""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    q = lambda sql: con.execute(sql).fetchone()[0]
    out = {
        "orders": q("SELECT COUNT(*) FROM orders"),
        "backorder_rate": q("SELECT AVG(status = 'Backordered') * 100 FROM orders"),
        "below_reorder": q("SELECT COUNT(*) FROM inventory WHERE on_hand_qty < reorder_point"),
        "skus": q("SELECT COUNT(*) FROM products"),
    }
    con.close()
    return out


def chart_options(df: pd.DataFrame) -> list[str]:
    """Decide which charts make sense for a result table."""
    if df is None or len(df) < 2:
        return []
    numeric = df.select_dtypes("number").columns.tolist()
    labels = [c for c in df.columns if c not in numeric]
    if not numeric or not labels:
        return []
    label = labels[0]
    looks_like_time = any(w in label.lower() for w in ("date", "month", "year", "week", "day")) \
        or df[label].astype(str).str.match(r"^\d{4}-\d{2}").all()
    options = ["Line", "Bar"] if looks_like_time else ["Bar"]
    values = df[numeric[0]]
    if not looks_like_time and len(df) <= 8 and (values >= 0).all():
        options.append("Pie")
    return options


def draw_chart(df: pd.DataFrame, kind: str):
    """Draw the first label column against the first numeric column."""
    numeric = df.select_dtypes("number").columns.tolist()
    label = [c for c in df.columns if c not in numeric][0]
    value = numeric[0]
    # Altair is fussy about names like COUNT(*), so use safe names and keep titles.
    data = pd.DataFrame({"label": df[label].astype(str), "value": df[value]})
    tooltip = [alt.Tooltip("label:N", title=label), alt.Tooltip("value:Q", title=value, format=",.2f")]

    if kind == "Pie":
        chart = (
            alt.Chart(data)
            .mark_arc(innerRadius=60, stroke="white")
            .encode(
                theta=alt.Theta("value:Q"),
                color=alt.Color("label:N", title=label, legend=alt.Legend(orient="right")),
                tooltip=tooltip,
            )
        )
    elif kind == "Line":
        chart = (
            alt.Chart(data)
            .mark_line(point=True)
            .encode(
                x=alt.X("label:O", title=label, sort=None),
                y=alt.Y("value:Q", title=value, axis=alt.Axis(tickCount=6)),
                tooltip=tooltip,
            )
        )
    else:
        chart = (
            alt.Chart(data)
            .mark_bar(cornerRadiusEnd=4)
            .encode(
                y=alt.Y("label:N", title=label, sort="-x"),
                x=alt.X("value:Q", title=value, axis=alt.Axis(tickCount=6)),
                color=alt.Color("value:Q", legend=None, scale=alt.Scale(scheme="blues")),
                tooltip=tooltip,
            )
        )
    st.altair_chart(chart.properties(height=320), width="stretch")


def ask(question: str):
    st.session_state.history.append(("user", question))
    with st.spinner("Writing SQL and running it…"):
        st.session_state.history.append(("assistant", answer(question)))


# ---------- state ----------
if "history" not in st.session_state:
    st.session_state.history = []

# ---------- sidebar ----------
with st.sidebar:
    st.header("Try a question")
    for i, ex in enumerate(EXAMPLES):
        if st.button(ex, key=f"ex{i}", width="stretch"):
            st.session_state.pending = ex
    st.divider()
    with st.expander("Database schema"):
        st.code(get_schema(), language="text")
    st.caption("🛡️ Read-only: the AI only proposes SQL. Every query is checked "
               "before it runs, and write commands are blocked.")
    if st.button("Clear conversation", width="stretch"):
        st.session_state.history = []
        st.rerun()

# ---------- header ----------
st.title("📊 Ops Analytics Copilot")
st.caption("Ask operational questions in plain English. The copilot writes read-only SQL, "
           "runs it, and explains the result, with the query shown for full transparency.")

k = kpis()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Orders (2025)", f"{k['orders']:,}")
c2.metric("Backorder rate", f"{k['backorder_rate']:.1f}%")
c3.metric("Stock lines below reorder point", f"{k['below_reorder']:,}")
c4.metric("Products", f"{k['skus']:,}")
st.divider()

# ---------- input ----------
typed = st.chat_input("Ask a question about the operations data…")
question = typed or st.session_state.pop("pending", None)
if question:
    ask(question)

if not st.session_state.history:
    st.info("Pick a question from the sidebar or type your own below.")

# ---------- conversation ----------
for n, (role, content) in enumerate(st.session_state.history):
    if role == "user":
        with st.chat_message("user"):
            st.write(content)
        continue

    with st.chat_message("assistant"):
        if content.get("blocked"):
            st.warning(f"🛡️ Query blocked by guardrail: {content['reason']}")
            st.code(content["sql"], language="sql")
            continue
        if content.get("error"):
            st.error(f"Query error: {content['error']}")
            st.code(content["sql"], language="sql")
            continue

        st.write(content["explanation"])
        rows = content["rows"] or []
        if not rows:
            st.caption("The query returned no rows.")
        else:
            df = pd.DataFrame(rows, columns=content["cols"])
            options = chart_options(df)
            tabs = st.tabs((["📈 Chart"] if options else []) + ["📋 Table", "🔎 SQL"])
            t = 0
            if options:
                with tabs[0]:
                    kind = st.segmented_control(
                        "Chart type", options, default=options[0],
                        key=f"chart{n}", label_visibility="collapsed",
                    ) or options[0]
                    draw_chart(df, kind)
                t = 1
            with tabs[t]:
                st.dataframe(df, width="stretch", hide_index=True)
                st.download_button(
                    "Download CSV", df.to_csv(index=False).encode(),
                    file_name="result.csv", mime="text/csv", key=f"dl{n}",
                )
            with tabs[t + 1]:
                st.code(content["sql"], language="sql")
            st.caption(f"{len(df):,} row{'s' if len(df) != 1 else ''} returned")
