"""เชื่อมต่อ PostgreSQL โดยตรง (ค่าเชื่อมต่อมาจาก environment variables)"""
import os

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text


@st.cache_resource
def get_engine():
    url = "postgresql+psycopg2://{u}:{p}@{h}:{port}/{db}".format(
        u=os.getenv("PGUSER", "airflow"),
        p=os.getenv("PGPASSWORD", "airflow"),
        h=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        db=os.getenv("PGDATABASE", "quake"),
    )
    return create_engine(url, pool_pre_ping=True)


@st.cache_data(ttl=60)
def query(sql: str, **params) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


def has_rows(table: str) -> bool:
    """ตารางมีอยู่และมีข้อมูลแล้วหรือยัง

    ไม่ cache: ระหว่างรอ DAG รอบแรก คำตอบเปลี่ยนจาก False เป็น True ได้ทุกเมื่อ
    ถ้า cache ไว้ เว็บจะยังขึ้น "ยังไม่มีข้อมูล" ต่ออีกถึง 60 วินาทีหลังข้อมูลเข้าแล้ว
    """
    assert table in {"earthquakes", "pipeline_runs"}, table  # ชื่อตารางมาจากโค้ดเท่านั้น
    with get_engine().connect() as conn:
        if not conn.execute(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"}).scalar():
            return False
        return bool(conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar())


def tables_ready() -> bool:
    return has_rows("earthquakes")
