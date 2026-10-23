"""หน้าเบื้องหลังระบบ (โบนัส: สถานะ pipeline): อ่านตาราง log ที่ DAG เขียนไว้ใน PostgreSQL"""
import pandas as pd
import plotly.express as px
import streamlit as st

from db import query
from theme import (SOURCE_COLORS, badge, card, chart, flow, page_header, paged_dataframe, section,
                   stat_strip)

SOURCE_NAMES = {"TMD": "กรมอุตุนิยมวิทยา", "USGS": "USGS", "EMSC": "EMSC"}
STATUS_TEXT = {"SUCCESS": "สำเร็จ", "PARTIAL": "บางแหล่งล่ม", "QUALITY_FAILED": "คุณภาพไม่ผ่าน",
               "FAILED": "ล้มเหลว"}

ready = query("SELECT to_regclass('public.pipeline_runs') IS NOT NULL AS ok")["ok"].iloc[0]
runs = query("SELECT * FROM pipeline_runs ORDER BY finished_at DESC") if ready else pd.DataFrame()
if runs.empty:
    page_header("Data pipeline · Apache Airflow", "ระบบนี้ทำงานยังไง")
    st.info("ยังไม่มีประวัติการรัน DAG")
    st.stop()

runs["finished_at"] = pd.to_datetime(runs["finished_at"], utc=True).dt.tz_convert("Asia/Bangkok")
latest = runs.iloc[0]
success_rate = (runs["status"] == "SUCCESS").mean()

page_header("Data pipeline · Apache Airflow · PostgreSQL", "ระบบนี้ทำงานยังไง",
            "ทุกตัวเลขในเว็บนี้มาจาก PostgreSQL ที่ DAG <code>earthquake_pipeline</code> ดึงจาก 3 หน่วยงาน "
            "ตรวจคุณภาพ และตัดเหตุการณ์ซ้ำให้อัตโนมัติทุก 30 นาที",
            [f"รอบล่าสุด {badge(latest['status'])}", f"<b>{len(runs)}</b> รอบที่บันทึกไว้"])

with card("ขั้นตอนของ Pipeline", "แต่ละขั้นคือ task ใน DAG · แหล่งไหนล่ม ขั้นที่เหลือยังทำงานต่อ"):
    flow([
        ("สร้างตาราง", "<code>create_tables</code> สร้างตารางใน PostgreSQL ถ้ายังไม่มี"),
        ("ดึงข้อมูล 3 แหล่ง", "TaskGroup <code>sources</code> TMD (scraping), USGS และ EMSC (API) รันขนานกัน"),
        ("รวมข้อมูล", "<code>merge</code> รวมเป็น schema เดียว แม้บางแหล่งจะล่ม"),
        ("ตรวจคุณภาพ", "<code>check_quality</code> ถ้าข้อมูลเสียเกิน 20% แยกไป <code>quarantine</code>"),
        ("โหลด (UPSERT)", "<code>load_raw</code> รันซ้ำแล้วจำนวนแถวไม่เพิ่ม"),
        ("ตัดซ้ำข้ามแหล่ง", "<code>dedup_publish</code> เวลาห่าง ≤ 60 วินาทีและระยะห่าง ≤ 100 กม."),
        ("บันทึกสถานะ", "<code>log_run</code> เขียนผลของรอบนี้ให้หน้านี้อ่าน"),
    ])

st.write("")
stat_strip([
    {"label": "รันล่าสุดเมื่อ", "value": latest["finished_at"].strftime("%H:%M"),
     "sub": latest["finished_at"].strftime("%d/%m/%Y")},
    {"label": "ดึงได้รอบล่าสุด", "value": f"{latest['rows_extracted']:,}", "unit": "แถว",
     "sub": f"ผ่านคุณภาพ {latest['rows_valid']:,} แถว"},
    {"label": "เหตุการณ์ในฐานข้อมูล", "value": f"{latest['events_total']:,}", "sub": "หลังตัดซ้ำข้ามแหล่ง"},
    {"label": "อัตราสำเร็จ", "value": f"{success_rate:.0%}", "sub": f"จาก {len(runs)} รอบ"},
])

# ------------------------------------------------------------- sources
section("แหล่งข้อมูลแต่ละแห่ง", "ผลการดึงข้อมูลในรอบล่าสุด และจำนวนแถวที่ได้ในแต่ละรอบ", kicker="แหล่งข้อมูล")
src = query("SELECT source, status, rows FROM pipeline_source_status WHERE run_id = :r ORDER BY source",
            r=latest["run_id"])
left, right = st.columns([2, 3], gap="medium")
with left, card("รอบล่าสุด", latest["note"] or "ทุกแหล่งตอบกลับปกติ"):
    tiles = "".join(
        f"<div class='tile'><div class='name'><span class='swatch' style='background:{SOURCE_COLORS[r.source]}'>"
        f"</span>{SOURCE_NAMES.get(r.source, r.source)}</div>"
        f"<div class='rows'>{r.rows:,} <small>แถว</small></div>{badge(r.status)}</div>"
        for r in src.itertuples())
    st.markdown(f"<div class='tiles tiles-stack'>{tiles}</div>", unsafe_allow_html=True)

with right, card("จำนวนแถวต่อแหล่งในแต่ละรอบ", "แท่งที่หายไปคือรอบที่แหล่งนั้นล่ม"):
    hist = query("""SELECT s.source, s.rows, r.finished_at
                    FROM pipeline_source_status s JOIN pipeline_runs r USING (run_id)
                    ORDER BY r.finished_at DESC LIMIT 150""")
    hist["finished_at"] = pd.to_datetime(hist["finished_at"], utc=True).dt.tz_convert("Asia/Bangkok")
    hist["run"] = hist["finished_at"].dt.strftime("%d/%m %H:%M")
    fig = px.bar(hist.sort_values("finished_at"), x="run", y="rows", color="source", barmode="group",
                 height=340, color_discrete_map=SOURCE_COLORS, labels={"run": "", "rows": "", "source": ""})
    fig.update_layout(legend=dict(orientation="h", y=1.12, x=0), bargap=0.3)
    chart(fig)

# ------------------------------------------------------------- history
section("ประวัติการรัน", "ทุกรอบที่ DAG บันทึกไว้ เรียงจากล่าสุด", kicker="Log")
with card("รอบที่ผ่านมา", f"{len(runs):,} รอบ"):
    paged_dataframe(
        runs.assign(status=runs["status"].map(lambda s: STATUS_TEXT.get(s, s)))
        [["finished_at", "status", "rows_extracted", "rows_valid", "rows_rejected", "events_total", "note", "run_id"]],
        column_config={
            "finished_at": st.column_config.DatetimeColumn("เวลา", format="DD/MM HH:mm"),
            "status": "สถานะ", "rows_extracted": "ดึงได้", "rows_valid": "ผ่าน", "rows_rejected": "ไม่ผ่าน",
            "events_total": "เหตุการณ์รวม", "note": st.column_config.TextColumn("หมายเหตุ", width="large"),
            "run_id": "run id"},
        key="runs")

rejected = query("SELECT source, source_event_id, reason, rejected_at FROM earthquakes_rejected "
                 "ORDER BY rejected_at DESC")
left, right = st.columns(2, gap="medium")
with left, card("รายการที่ไม่ผ่านการตรวจคุณภาพ", "ถูกกักไว้ในตาราง earthquakes_rejected ไม่นำเข้าตารางหลัก"):
    if rejected.empty:
        st.markdown(f"{badge('success')} &nbsp;ยังไม่มีรายการที่ถูกกักไว้", unsafe_allow_html=True)
    else:
        paged_dataframe(rejected, key="rejected",
                        column_config={"source": "แหล่ง", "source_event_id": "รหัส", "reason": "เหตุผล",
                                       "rejected_at": st.column_config.DatetimeColumn("เวลา", format="DD/MM HH:mm")})

with right, card("แหล่งข้อมูล", "ข้อมูลทางธรณีวิทยาเท่านั้น ไม่มีข้อมูลส่วนบุคคล (PDPA)"):
    st.markdown(
        "<ul class='sources'>"
        "<li><b>กรมอุตุนิยมวิทยา</b> — web scraping หน้า <a href='https://earthquake.tmd.go.th/inside.html' "
        "target='_blank'>แผ่นดินไหวในประเทศและใกล้เคียง</a> ด้วย requests + BeautifulSoup (ตรวจ robots.txt ทุกครั้ง)</li>"
        "<li><b>USGS</b> — <a href='https://earthquake.usgs.gov/fdsnws/event/1/' target='_blank'>FDSN Event API</a> "
        "(GeoJSON)</li>"
        "<li><b>EMSC</b> — <a href='https://www.seismicportal.eu/fdsnws/event/1/' target='_blank'>Seismic Portal "
        "FDSN API</a> (JSON)</li>"
        "</ul>",
        unsafe_allow_html=True)
