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


def tables_ready() -> bool:
    df = query("SELECT to_regclass('public.earthquakes') IS NOT NULL AS ok")
    return bool(df["ok"].iloc[0])
