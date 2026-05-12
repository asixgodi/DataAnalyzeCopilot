import sqlite3
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[4]
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "demo.db"


def get_connection() -> sqlite3.Connection:
    ensure_demo_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_demo_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(
            """
            CREATE TABLE products (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              category TEXT NOT NULL,
              price REAL NOT NULL
            );

            CREATE TABLE orders (
              id INTEGER PRIMARY KEY,
              product_id INTEGER NOT NULL,
              month TEXT NOT NULL,
              quantity INTEGER NOT NULL,
              amount REAL NOT NULL,
              FOREIGN KEY(product_id) REFERENCES products(id)
            );

            CREATE TABLE refunds (
              id INTEGER PRIMARY KEY,
              order_id INTEGER NOT NULL,
              reason TEXT NOT NULL,
              status TEXT NOT NULL,
              refund_amount REAL NOT NULL,
              FOREIGN KEY(order_id) REFERENCES orders(id)
            );

            CREATE TABLE reviews (
              id INTEGER PRIMARY KEY,
              product_id INTEGER NOT NULL,
              rating INTEGER NOT NULL,
              content TEXT NOT NULL,
              month TEXT NOT NULL,
              FOREIGN KEY(product_id) REFERENCES products(id)
            );

            CREATE TABLE tickets (
              id INTEGER PRIMARY KEY,
              product_id INTEGER NOT NULL,
              category TEXT NOT NULL,
              reason TEXT NOT NULL,
              priority TEXT NOT NULL,
              month TEXT NOT NULL,
              FOREIGN KEY(product_id) REFERENCES products(id)
            );
            """
        )

        products = [
            (1, "轻薄防晒衣", "服装", 199),
            (2, "通勤衬衫", "服装", 159),
            (3, "缓震跑鞋", "鞋靴", 399),
            (4, "皮质短靴", "鞋靴", 499),
            (5, "蓝牙耳机", "数码", 299),
            (6, "智能手表", "数码", 699),
        ]
        conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", products)

        order_rows: list[tuple[int, int, str, int, float]] = []
        refund_rows: list[tuple[int, int, str, str, float]] = []
        review_rows: list[tuple[int, int, int, str, str]] = []
        ticket_rows: list[tuple[int, int, str, str, str, str]] = []
        order_id = refund_id = review_id = ticket_id = 1

        volumes = {
            "2026-03": {"服装": (260, 22), "鞋靴": (180, 13), "数码": (150, 8)},
            "2026-04": {"服装": (310, 52), "鞋靴": (190, 18), "数码": (160, 10)},
            "2026-05": {"服装": (280, 30), "鞋靴": (210, 22), "数码": (170, 12)},
        }
        product_by_category = {
            "服装": [1, 2],
            "鞋靴": [3, 4],
            "数码": [5, 6],
        }
        refund_reasons = {
            "服装": ["尺码偏小", "色差明显", "面料过薄"],
            "鞋靴": ["磨脚", "尺码偏大", "鞋底偏硬"],
            "数码": ["续航不达预期", "连接不稳定", "包装破损"],
        }

        for month, category_map in volumes.items():
            for category, (orders_count, refunds_count) in category_map.items():
                product_ids = product_by_category[category]
                for idx in range(orders_count):
                    product_id = product_ids[idx % len(product_ids)]
                    price = products[product_id - 1][3]
                    order_rows.append((order_id, product_id, month, 1, price))
                    if idx < refunds_count:
                        reason = refund_reasons[category][idx % len(refund_reasons[category])]
                        refund_rows.append((refund_id, order_id, reason, "approved", price))
                        refund_id += 1
                    if idx < 28:
                        rating = 2 if idx < refunds_count // 2 else 4
                        content = refund_reasons[category][idx % len(refund_reasons[category])]
                        review_rows.append((review_id, product_id, rating, content, month))
                        review_id += 1
                    if idx < 18:
                        reason = refund_reasons[category][idx % len(refund_reasons[category])]
                        ticket_rows.append((ticket_id, product_id, "售后", reason, "P1" if idx < 6 else "P2", month))
                        ticket_id += 1
                    order_id += 1

        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", order_rows)
        conn.executemany("INSERT INTO refunds VALUES (?, ?, ?, ?, ?)", refund_rows)
        conn.executemany("INSERT INTO reviews VALUES (?, ?, ?, ?, ?)", review_rows)
        conn.executemany("INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?)", ticket_rows)
        conn.commit()
    finally:
        conn.close()
