"""จุดเริ่มของเว็บ: ตั้งค่าหน้า ธีม และแถบเมนูด้านบน แล้วเรียกหน้าที่เลือก"""
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Quake Monitor", page_icon=str(Path(__file__).parent / "static" / "logo.png"),
                   layout="wide", initial_sidebar_state="collapsed")

from db import query  # noqa: E402  (ต้องเรียก set_page_config ก่อน)
from theme import apply_theme, footer, top_nav  # noqa: E402

pages = [
    st.Page("views/dashboard.py", title="ภาพรวม", url_path="overview", default=True),
    st.Page("views/analysis.py", title="วิเคราะห์", url_path="analysis"),
    st.Page("views/status.py", title="เบื้องหลังระบบ", url_path="pipeline"),
]
current = st.navigation(pages, position="hidden")


def freshness() -> str:
    try:
        t = query("SELECT max(finished_at) AS t FROM pipeline_runs")["t"].iloc[0]
    except Exception:  # ตารางยังไม่ถูกสร้าง (DAG ยังไม่เคยรัน)
        return ""
    if pd.isna(t):
        return ""
    return "อัปเดตล่าสุด " + pd.Timestamp(t).tz_convert("Asia/Bangkok").strftime("%d/%m/%Y %H:%M")


apply_theme()
top_nav(pages, current, freshness())
current.run()
footer()
