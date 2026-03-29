import sqlite3
import pandas as pd
from pathlib import Path


class CacheDB:
    """SQLite 本地数据缓存"""

    def __init__(self, db_path: str = "data/cache/macro.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cpi (
                series_id TEXT NOT NULL,
                date TEXT NOT NULL,
                year INTEGER,
                month INTEGER,
                value REAL,
                yoy_pct REAL,
                mom_pct REAL,
                PRIMARY KEY (series_id, date)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS fred_us (
                series_id TEXT NOT NULL,
                date TEXT NOT NULL,
                value REAL,
                yoy_pct REAL,
                mom_pct REAL,
                PRIMARY KEY (series_id, date)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS china_macro (
                indicator TEXT NOT NULL,
                date TEXT NOT NULL,
                value REAL,
                yoy_pct REAL,
                mom_pct REAL,
                extra TEXT,
                PRIMARY KEY (indicator, date)
            )
        """)
        self.conn.commit()

    def save(self, table: str, df: pd.DataFrame):
        """保存 DataFrame 到指定表，使用 INSERT OR REPLACE 避免重复"""
        if df.empty:
            return
        df_copy = df.copy()
        if "date" in df_copy.columns:
            df_copy["date"] = df_copy["date"].astype(str)
        df_copy.to_sql(table, self.conn, if_exists="append", index=False,
                       method=self._upsert_method(table))

    def _upsert_method(self, table: str):
        def method(pd_table, conn, keys, data_iter):
            cols = ", ".join(keys)
            placeholders = ", ".join(["?"] * len(keys))
            sql = f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})"
            data = [row for row in data_iter]
            conn.executemany(sql, data)
        return method

    def load(self, table: str, series_id: str | None = None) -> pd.DataFrame:
        """从缓存加载数据"""
        try:
            id_col = "indicator" if table == "china_macro" else "series_id"
            if series_id:
                df = pd.read_sql(
                    f"SELECT * FROM {table} WHERE {id_col} = ? ORDER BY date",
                    self.conn,
                    params=[series_id],
                )
            else:
                df = pd.read_sql(f"SELECT * FROM {table} ORDER BY date", self.conn)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception:
            return pd.DataFrame()

    def close(self):
        self.conn.close()
