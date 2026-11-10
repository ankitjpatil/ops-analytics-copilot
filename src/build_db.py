"""
build_db.py — creates a realistic operations/retail SQLite database.

Run once:  python src/build_db.py
Produces:  data/operations.db  (gitignored — regenerated from this script)

The data is synthetic but intentionally realistic, with a few patterns baked in
so the analytics copilot has genuine things to find (stockouts clustered in a
category, one warehouse with more discrepancies, seasonal order spikes).
"""
import sqlite3
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)  # reproducible

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "operations.db"

CATEGORIES = ["Fasteners", "Seals", "Electronics", "Packaging", "Lubricants", "Tooling"]
WAREHOUSES = ["Scarborough-DC", "Ajax-DC", "Barrie-DC", "Mississauga-DC"]

def build():
    DB_PATH.parent.mkdir(exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # --- schema ---
    cur.executescript("""
    CREATE TABLE products (
        sku            TEXT PRIMARY KEY,
        description    TEXT NOT NULL,
        category       TEXT NOT NULL,
        unit_cost      REAL NOT NULL
    );
    CREATE TABLE warehouses (
        warehouse_id   TEXT PRIMARY KEY,
        name           TEXT NOT NULL,
        region         TEXT NOT NULL
    );
    CREATE TABLE inventory (
        sku            TEXT NOT NULL,
        warehouse_id   TEXT NOT NULL,
        on_hand_qty    INTEGER NOT NULL,
        reorder_point  INTEGER NOT NULL,
        PRIMARY KEY (sku, warehouse_id),
        FOREIGN KEY (sku) REFERENCES products(sku),
        FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
    );
    CREATE TABLE orders (
        order_id       INTEGER PRIMARY KEY,
        sku            TEXT NOT NULL,
        warehouse_id   TEXT NOT NULL,
        order_date     TEXT NOT NULL,
        quantity       INTEGER NOT NULL,
        status         TEXT NOT NULL,   -- Fulfilled / Backordered / Cancelled
        FOREIGN KEY (sku) REFERENCES products(sku),
        FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
    );
    """)

    # --- warehouses ---
    regions = {"Scarborough-DC": "East GTA", "Ajax-DC": "Durham",
               "Barrie-DC": "Simcoe", "Mississauga-DC": "West GTA"}
    cur.executemany("INSERT INTO warehouses VALUES (?,?,?)",
                    [(w, w.replace("-DC", " Distribution"), regions[w]) for w in WAREHOUSES])

    # --- products ---
    products = []
    for i in range(1, 121):
        cat = random.choice(CATEGORIES)
        sku = f"{cat[:3].upper()}-{i:04d}"
        cost = round(random.uniform(0.5, 250), 2)
        products.append((sku, f"{cat} item {i}", cat, cost))
    cur.executemany("INSERT INTO products VALUES (?,?,?,?)", products)

    # --- inventory (pattern: Electronics runs lean; Barrie-DC understocked) ---
    inv = []
    for sku, desc, cat, cost in products:
        for w in WAREHOUSES:
            reorder = random.randint(20, 80)
            base = random.randint(0, 200)
            if cat == "Electronics":
                base = int(base * 0.4)          # electronics tend to be low
            if w == "Barrie-DC":
                base = int(base * 0.6)          # this DC runs understocked
            inv.append((sku, w, max(0, base), reorder))
    cur.executemany("INSERT INTO inventory VALUES (?,?,?,?)", inv)

    # --- orders (pattern: Q4 spike; Electronics backorders higher) ---
    orders = []
    oid = 1
    start = date(2025, 1, 1)
    for _ in range(4000):
        d = start + timedelta(days=random.randint(0, 364))
        sku, desc, cat, cost = random.choice(products)
        w = random.choice(WAREHOUSES)
        qty = random.randint(1, 40)
        # seasonal spike in Nov/Dec
        if d.month in (11, 12) and random.random() < 0.4:
            qty = int(qty * 1.8)
        # status pattern
        r = random.random()
        if cat == "Electronics":
            status = "Backordered" if r < 0.22 else ("Cancelled" if r < 0.28 else "Fulfilled")
        else:
            status = "Backordered" if r < 0.08 else ("Cancelled" if r < 0.12 else "Fulfilled")
        orders.append((oid, sku, w, d.isoformat(), qty, status))
        oid += 1
    cur.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)", orders)

    con.commit()
    # quick sanity output
    for t in ["products", "warehouses", "inventory", "orders"]:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:12} {n:>6} rows")
    con.close()
    print(f"\nDatabase written to {DB_PATH}")

if __name__ == "__main__":
    build()
