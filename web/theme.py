"""ธีมและ component ของเว็บ อิงจาก DESIGN.md (ดู web/DESIGN.md) แนว Starbucks:
พื้นครีมอุ่น, เขียวสี่ระดับตามหน้าที่, ปุ่มแคปซูลเต็ม, การ์ดมุม 12px เงาบางมาก, กดแล้วยุบ scale(.95)

ลำดับชั้นของทุกหน้า:
  page_header()  eyebrow + H1 + คำอธิบาย + แถบข้อมูลสั้น (meta pills)
  kpis()         แถวการ์ดตัวเลขสำคัญ
  section()      หัวข้อส่วน (H2 + คำอธิบาย)
  card()         การ์ดครอบข้อมูลแต่ละชุด (หัวการ์ด + เนื้อหา)
  footer()
"""
import base64
import hashlib
import math
from contextlib import contextmanager
from html import escape
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

C = {
    "canvas": "#F2F0EB",   # neutral warm: พื้นหลังหน้า
    "surface": "#EDEBE9",  # ceramic: พื้นรอง, ฉากกราฟ 3 มิติ
    "white": "#FFFFFF",    # การ์ด
    "ink": "#1F1F1F",      # ตัวอักษรหลัก (ดำ 87% บนครีม)
    "charcoal": "#33433D",  # slate green: ตัวอักษรรอง
    "muted": "#6E6E6B",    # ดำ 58%: คำอธิบาย/label
    "line": "#E2DFD8",
    "taupe": "#C9D9D2",    # sage อ่อน: ข้อมูลที่ไม่ใช่จุดเด่น
    "mint": "#D4E9E2",     # green light
    "brand": "#006241",    # Starbucks green: หัวข้อหลัก
    "accent": "#00754A",   # green accent: ปุ่มหลัก, จุดเด่นของข้อมูล
    "accent2": "#5FA383",  # เขียวกลางสำหรับไล่สี
    "accent3": "#CBA258",  # gold: ใช้เฉพาะสีของข้อมูลเพื่อแยกแหล่ง
    "house": "#1E3932",    # house green: แถบเข้ม, footer, การ์ดเด่น
    "uplift": "#2B5148",
    "clay": "#1E3932",
    "ok": "#006241",
    "red": "#C82014",
}
SOURCE_COLORS = {"TMD": C["accent"], "USGS": C["house"], "EMSC": C["accent3"]}
SEQ_SCALE = [C["mint"], C["accent2"], C["accent"], C["house"]]
# ขนาดแผ่นดินไหวใช้โทนอุ่น (เหลือง → แดง) เพราะคนอ่านสีเขียวเข้มว่า "ปลอดภัย" ซึ่งกลับความหมาย
MAG_SCALE = ["#FCE7A2", "#F6B04D", "#E8702A", "#C2321C", "#7F1D12"]
FONT = "'Nunito Sans', 'IBM Plex Sans Thai', 'Helvetica Neue', Arial, sans-serif"
EASE = "cubic-bezier(.2,.7,.2,1)"
CARD_SHADOW = "0 0 .5px rgba(0,0,0,.14), 0 1px 1px rgba(0,0,0,.24)"
LIFT_SHADOW = "0 0 6px rgba(0,0,0,.16), 0 8px 12px rgba(0,0,0,.10)"

pio.templates["quake"] = go.layout.Template(layout=dict(
    font=dict(family=FONT, color=C["ink"], size=13),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    colorway=[C["accent"], C["house"], C["accent3"], C["accent2"], C["muted"]],
    xaxis=dict(gridcolor=C["line"], zerolinecolor=C["line"], linecolor=C["line"],
               tickfont=dict(color=C["muted"]), title_font=dict(color=C["muted"], size=12)),
    yaxis=dict(gridcolor=C["line"], zerolinecolor=C["line"], linecolor=C["line"],
               tickfont=dict(color=C["muted"]), title_font=dict(color=C["muted"], size=12)),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=C["muted"], size=12), title_text=""),
    hoverlabel=dict(bgcolor=C["white"], bordercolor=C["line"], font=dict(family=FONT, color=C["ink"])),
    margin=dict(l=0, r=0, t=8, b=0),
))
pio.templates.default = "plotly_white+quake"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;500;600;700&family=Nunito+Sans:opsz,wght@6..12,400;6..12,600;6..12,700;6..12,800&display=swap');

/* ---------- base ---------- */
html, body, [class*="css"], .stMarkdown, button, input, textarea {{ font-family: {FONT}; letter-spacing: -0.01em; }}
.block-container {{ padding-top: 2rem; padding-bottom: 3rem; max-width: 1280px; }}
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stAppDeployButton"] {{ display: none; }}
header[data-testid="stHeader"] {{ background: transparent; }}
h1, h2, h3, h4 {{ font-family: {FONT}; color: {C['ink']}; letter-spacing: -0.01em; }}
a {{ color: {C['accent']}; }}

/* ---------- top bar: เต็มความกว้าง ติดด้านบน (แบบเว็บค่าครองชีพ) ---------- */
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], header[data-testid="stHeader"] {{ display: none; }}
.block-container {{ padding-top: 0 !important; }}
.st-key-topnav {{ position: sticky; top: 0; z-index: 999; padding: 12px 0; margin-bottom: 44px;
    background: {C['canvas']}; box-shadow: 0 0 0 100vmax {C['canvas']}, 0 1px 0 100vmax {C['line']};
    clip-path: inset(0 -100vmax -1px -100vmax); }}
.st-key-topnav [data-testid="stHorizontalBlock"] {{ align-items: center; gap: 6px; flex-wrap: nowrap; }}
.st-key-topnav [data-testid="stColumn"] {{ flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }}
.st-key-topnav [data-testid="stColumn"]:first-child {{ flex: 1 1 auto !important; overflow-x: clip; overflow-y: visible; }}
.brand {{ display: flex; align-items: center; gap: 12px; white-space: nowrap; }}
.brand .logo {{ flex-shrink: 0; width: 46px; height: 46px; display: block; }}
.brand .text {{ display: flex; flex-direction: column; line-height: 1.25; }}
.brand .text strong {{ font-size: 18px; font-weight: 800; color: {C['house']}; }}
.brand .text small {{ font-size: 12.5px; color: {C['muted']}; font-weight: 600; }}
.st-key-topnav [data-testid="stPageLink"] a {{ justify-content: center; border-radius: 999px; padding: 8px 18px;
    border: 1px solid transparent; background: transparent;
    transition: background-color .2s ease, border-color .2s ease, transform .2s ease; }}
.st-key-topnav [data-testid="stPageLink"] a p {{ font-size: 15px; font-weight: 700; color: {C['ink']}; white-space: nowrap; }}
.st-key-topnav [data-testid="stPageLink"] a:hover {{ background: {C['white']}; border-color: {C['line']}; }}
.st-key-topnav [data-testid="stPageLink"] a:active {{ transform: scale(.95); }}
.st-key-topnav [class*="st-key-nav-active"] a, .st-key-topnav [class*="st-key-nav-active"] a:hover {{
    background: {C['accent']}; border-color: {C['accent']}; }}
.st-key-topnav [class*="st-key-nav-active"] a p {{ color: {C['white']}; }}
.st-key-topnav [class*="st-key-nav-airflow"] a {{ border-color: {C['accent']}; }}
.st-key-topnav [class*="st-key-nav-airflow"] a p {{ color: {C['accent']}; }}
@media (max-width: 900px) {{
  .brand .text small {{ display: none; }}
  .st-key-topnav [data-testid="stPageLink"] a {{ padding: 6px 12px; }}
  .st-key-topnav [class*="st-key-nav-airflow"] {{ display: none; }}
}}
@media (max-width: 600px) {{ .brand .text {{ display: none; }} }}

/* ---------- page header ---------- */
.eyebrow {{ text-transform: uppercase; letter-spacing: .1em; font-size: 13px; font-weight: 800;
           color: {C['accent']}; margin: 0 0 8px; }}
.page-title {{ font-size: 40px; font-weight: 800; line-height: 1.35; margin: 0 0 10px; color: {C['brand']};
              letter-spacing: -0.01em; }}
.page-lede {{ font-size: 18px; color: {C['muted']}; max-width: 720px; margin: 0 0 18px; line-height: 1.7; }}
.meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 28px; }}
.meta > span {{ display: inline-flex; align-items: center; gap: 6px; background: {C['white']}; border-radius: 999px;
    padding: 6px 16px; font-size: 13.5px; color: {C['charcoal']}; font-weight: 600; box-shadow: {CARD_SHADOW}; }}
.meta .badge {{ margin: 0; padding: 1px 10px; }}
.meta span b {{ font-weight: 800; color: {C['house']}; }}

/* ---------- section head: kicker + H2 ใหญ่ + คำอธิบาย / ตัวควบคุมชิดขวา ---------- */
.section {{ margin: 56px 0 6px; }}
.section .kicker {{ text-transform: uppercase; letter-spacing: .1em; font-size: 13px; font-weight: 800; color: {C['accent']}; }}
.section h2 {{ font-size: 30px; font-weight: 800; margin: 2px 0 0; padding: 0; line-height: 1.35; color: {C['house']}; }}
.section p {{ color: {C['muted']}; margin: 4px 0 0; font-size: 15px; }}
[class*="st-key-sechead-"] {{ margin-top: 56px; }}
[class*="st-key-sechead-"] .section {{ margin: 0; }}
.note {{ color: {C['muted']}; font-size: 14px; line-height: 1.7; max-width: 900px; margin: 4px 0 0; }}

/* ---------- hero (หน้าภาพรวม) ---------- */
.hero-kicker {{ text-transform: uppercase; letter-spacing: .1em; font-size: 13px; font-weight: 800; color: {C['accent']}; }}
.hero-title {{ font-size: clamp(32px, 3.6vw, 50px); font-weight: 800; line-height: 1.4; color: {C['house']}; margin: 10px 0 14px; }}
.hero-title .num {{ color: {C['accent']}; }}
.hero-lede {{ font-size: 18px; line-height: 1.7; color: {C['muted']}; max-width: 640px; margin: 0 0 8px; }}
.hero-lede b {{ color: {C['ink']}; }}
.hero-mini {{ font-size: 13px; font-weight: 700; color: {C['muted']}; margin-top: 14px; }}

/* การ์ดเด่น: เหตุการณ์ล่าสุด */
.feature {{ background: {C['house']}; color: {C['white']}; border-radius: 12px; padding: 28px 30px; min-height: 100%;
    box-sizing: border-box; display: flex; flex-direction: column; gap: 10px; position: relative; overflow: hidden;
    box-shadow: {LIFT_SHADOW}; }}
.feature::after {{ content: ""; position: absolute; right: -60px; top: -60px; width: 200px; height: 200px; border-radius: 50%;
    border: 28px solid rgba(255,255,255,.06); }}
.feature .kicker {{ text-transform: uppercase; letter-spacing: .1em; font-size: 12.5px; font-weight: 800; color: {C['accent3']}; }}
.feature .mag {{ font-size: 64px; font-weight: 800; line-height: 1; }}
.feature .mag small {{ font-size: 18px; font-weight: 700; color: rgba(255,255,255,.7); margin-left: 6px; }}
.feature .place {{ font-size: 20px; font-weight: 800; line-height: 1.4; }}
.feature .rows {{ display: grid; grid-template-columns: auto 1fr; gap: 6px 16px; font-size: 14px; color: rgba(255,255,255,.75); }}
.feature .rows b {{ color: {C['white']}; font-weight: 700; }}
.feature .chips {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: auto; padding-top: 8px; }}
.feature .chips span {{ border: 1px solid rgba(255,255,255,.35); border-radius: 999px; padding: 3px 12px; font-size: 12.5px; font-weight: 700; }}

/* แถบตัวเลขสำคัญ: หลายช่องต่อกันเป็นแถบเดียว */
.stat-strip {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); background: {C['white']}; border-radius: 12px;
    box-shadow: {CARD_SHADOW}; overflow: hidden; margin-top: 8px; }}
.stat-strip .cell {{ padding: 22px 26px; border-left: 1px solid {C['line']}; transition: background-color .2s ease; min-width: 0; }}
.stat-strip .cell:first-child {{ border-left: 0; }}
.stat-strip .cell:hover {{ background: {C['canvas']}; }}
.stat-strip .label {{ font-size: 13px; font-weight: 700; color: {C['muted']}; }}
.stat-strip .value {{ font-size: 32px; font-weight: 800; color: {C['house']}; line-height: 1.25; margin-top: 6px; }}
.stat-strip .value small {{ font-size: 15px; color: {C['muted']}; font-weight: 600; margin-left: 4px; }}
.stat-strip .sub {{ font-size: 13px; color: {C['muted']}; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
@media (max-width: 1100px) {{
  .stat-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .stat-strip .cell:nth-child(3) {{ border-left: 0; }}
  .stat-strip .cell:nth-child(n+3) {{ border-top: 1px solid {C['line']}; }}
}}

/* ขั้นตอน pipeline เรียงเป็นแถวมีลูกศร */
.flow {{ list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(128px, 1fr)); gap: 14px; }}
@media (max-width: 1100px) {{ .flow li::after {{ display: none; }} }}
.flow li {{ position: relative; background: {C['canvas']}; border-radius: 12px; padding: 14px 16px; }}
.flow li .n {{ display: inline-flex; width: 26px; height: 26px; border-radius: 50%; background: {C['accent']}; color: {C['white']};
    align-items: center; justify-content: center; font-size: 13px; font-weight: 800; margin-bottom: 8px; }}
.flow li b {{ display: block; font-size: 14.5px; color: {C['house']}; }}
.flow li span {{ display: block; font-size: 13px; color: {C['muted']}; line-height: 1.5; margin-top: 4px; }}
.flow li:not(:last-child)::after {{ content: "→"; position: absolute; right: -12px; top: 18px; color: {C['accent']};
    font-weight: 800; z-index: 1; }}
.sources {{ margin: 0; padding-left: 20px; line-height: 1.8; font-size: 14.5px; color: {C['charcoal']}; }}
.sources b {{ color: {C['house']}; }}

/* ---------- KPI cards ---------- */
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 16px; }}
.kpi {{ background: {C['white']}; border-radius: 12px; padding: 20px 22px; box-shadow: {CARD_SHADOW};
       position: relative; overflow: hidden; transition: transform .25s {EASE}, box-shadow .25s {EASE}; }}
.kpi::before {{ content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: {C['mint']};
               transition: background-color .25s ease; }}
.kpi:hover {{ transform: translateY(-3px); box-shadow: {LIFT_SHADOW}; }}
.kpi:hover::before {{ background: {C['accent']}; }}
.kpi .label {{ font-size: 12px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; color: {C['muted']}; }}
.kpi .value {{ font-size: 36px; font-weight: 800; line-height: 1.2; margin-top: 8px; color: {C['house']}; }}
.kpi .value small {{ font-size: 15px; color: {C['muted']}; font-weight: 600; margin-left: 4px; }}
.kpi .sub {{ font-size: 13px; color: {C['muted']}; margin-top: 4px; white-space: nowrap; overflow: hidden;
            text-overflow: ellipsis; }}
.kpi.accent {{ background: {C['house']}; }}
.kpi.accent::before {{ background: {C['accent3']}; }}
.kpi.accent .label, .kpi.accent .sub, .kpi.accent .value small {{ color: rgba(255,255,255,.70); }}
.kpi.accent .value {{ color: {C['white']}; }}

/* ---------- cards: st.container(border=True, key="card-...") ----------
   ใช้กรอบ border ของ Streamlit เอง เพราะ Streamlit หัก padding ของกรอบนี้ออกตอนคำนวณความกว้างให้กราฟ/ตาราง
   ห้ามเพิ่ม padding ให้กรอบเองอีก ไม่อย่างนั้นเนื้อหาจะล้นขอบขวาของการ์ด */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [class*="st-key-card-"]) {{
    background: {C['white']}; border: 0 !important; border-radius: 12px !important; box-shadow: {CARD_SHADOW};
    transition: box-shadow .3s {EASE}; }}
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [class*="st-key-card-"]):hover {{ box-shadow: {LIFT_SHADOW}; }}
[class*="st-key-card-"] {{ gap: 10px; }}
[class*="st-key-card-"] iframe {{ width: 100% !important; border-radius: 12px; }}  /* components.html ตั้งกว้าง 300px ไว้ก่อน */

/* การ์ดที่วางเคียงกันในคอลัมน์สูงเท่ากันเสมอ (หนึ่งคอลัมน์ = หนึ่งการ์ด) */
[data-testid="stHorizontalBlock"]:has([class*="st-key-card-"]) {{ align-items: stretch; }}
[data-testid="stColumn"]:has([class*="st-key-card-"]) > [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stColumn"]:has([class*="st-key-card-"]) > [data-testid="stVerticalBlockBorderWrapper"] > div,
[data-testid="stColumn"]:has([class*="st-key-card-"]) > [data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"],
[data-testid="stColumn"]:has([class*="st-key-card-"]) > [data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"]:only-child {{
    height: 100%; }}

.card-head {{ margin-bottom: 4px; padding: 2px 4px 0; }}
.card-head h4 {{ font-size: 18px; font-weight: 800; margin: 0; padding: 0; line-height: 1.45; color: {C['house']}; }}
.card-head p {{ font-size: 14px; color: {C['muted']}; margin: 2px 0 0; }}
.card-note {{ background: {C['canvas']}; border-radius: 12px; padding: 12px 16px; margin-top: 4px; font-size: 14.5px;
             color: {C['charcoal']}; line-height: 1.7; }}
.card-note b {{ color: {C['brand']}; }}

/* ---------- source status tiles ---------- */
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
.tiles-stack {{ grid-template-columns: 1fr; }}
.st-key-viewbar [data-testid="stButtonGroup"] > div {{ margin-left: auto; }}
.tile {{ border-radius: 12px; padding: 16px 18px; background: {C['canvas']};
        transition: transform .25s {EASE}, box-shadow .25s {EASE}, background-color .25s ease; }}
.tile:hover {{ transform: translateY(-2px); background: {C['white']}; box-shadow: {LIFT_SHADOW}; }}
.tile .name {{ font-weight: 800; font-size: 15px; display: flex; align-items: center; gap: 8px; color: {C['house']}; }}
.tile .rows {{ font-size: 28px; font-weight: 800; margin-top: 6px; color: {C['ink']}; }}
.tile .rows small {{ font-size: 14px; color: {C['muted']}; font-weight: 600; }}
.swatch {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
.badge {{ display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 3px 12px;
         font-size: 12.5px; font-weight: 700; margin-top: 8px; }}
.badge::before {{ content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }}
.badge.ok {{ background: {C['mint']}; color: {C['brand']}; }}
.badge.warn {{ background: #FAF6EE; color: #8A6A2B; box-shadow: inset 0 0 0 1px #DFC49D; }}
.badge.fail {{ background: #FBEAE8; color: {C['red']}; }}

/* ---------- ป้ายระดับความรุนแรง ---------- */
.sev {{ display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 3px 12px;
       font-size: 12.5px; font-weight: 800; white-space: nowrap; }}
.sev::before {{ content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }}
.sev.s1 {{ background: #EEF2F0; color: #5B6B64; }}
.sev.s2 {{ background: {C['mint']}; color: {C['brand']}; }}
.sev.s3 {{ background: #FAF1DC; color: #8A6A2B; }}
.sev.s4 {{ background: #FCE3D6; color: #B4400F; }}
.sev.s5 {{ background: #FBE0DD; color: {C['red']}; }}
.feature .sev {{ align-self: flex-start; }}
.sev-legend {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 12.5px; color: {C['muted']}; }}

/* ---------- เทียบรายงานของแต่ละแหล่ง ---------- */
.cmp-table {{ width: 100%; border-collapse: separate; border-spacing: 0; font-size: 14px; table-layout: fixed; }}
.cmp-table, .cmp-table tr, .cmp-table th, .cmp-table td {{ border: 0 !important; background: transparent; }}
.cmp-table th, .cmp-table td {{ padding: 9px 12px; text-align: left; border-bottom: 1px solid {C['line']} !important; }}
.cmp-table thead th {{ font-size: 14px; font-weight: 800; color: {C['house']}; vertical-align: bottom; line-height: 1.5;
    border-bottom: 2px solid var(--c, {C['line']}) !important; }}
.cmp-table thead th i {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%; background: var(--c);
    margin-right: 7px; }}
.cmp-table thead th:first-child {{ width: 24%; border-bottom-color: transparent !important; }}
.cmp-table .ref {{ display: table; margin: 4px 0 0 16px; background: {C['mint']}; color: {C['brand']}; border-radius: 999px;
    padding: 1px 8px; font-size: 11.5px; font-weight: 800; vertical-align: 1px; }}
.cmp-table tbody th {{ color: {C['muted']}; font-weight: 700; font-size: 13px; white-space: nowrap; }}
.cmp-table td {{ color: {C['ink']}; font-weight: 600; font-variant-numeric: tabular-nums; }}
.cmp-table td.big {{ font-size: 24px; font-weight: 800; color: {C['house']}; }}
.cmp-table td.na {{ color: {C['muted']}; font-weight: 500; }}
.cmp-table td.id {{ font-size: 12.5px; color: {C['muted']}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.cmp-table tbody tr {{ transition: background-color .2s ease; }}
.cmp-table tbody tr:hover {{ background: {C['canvas']}; }}
.card-head p .sev {{ margin-left: 6px; vertical-align: 1px; padding: 1px 10px; }}
.card-head p {{ line-height: 1.9; }}
.hint {{ margin: 2px 0 4px; }}
.diffs {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 18px; }}
.diffs span {{ background: {C['white']}; box-shadow: inset 0 0 0 1px {C['line']}; border-radius: 999px; padding: 5px 14px;
              font-size: 13px; color: {C['charcoal']}; }}
.diffs b {{ color: {C['house']}; }}
.hint {{ font-size: 13.5px; color: {C['muted']}; }}
.hint b {{ color: {C['accent']}; }}

/* ---------- buttons (ทุกปุ่ม: แคปซูลเต็ม, กดแล้วยุบ) ---------- */
button {{ transition: all .2s ease !important; }}
button:active:not(:disabled) {{ transform: scale(.95); }}
[data-testid^="stBaseButton-secondary"] {{ border-radius: 50px !important; border: 1px solid {C['accent']} !important;
    background: transparent !important; color: {C['accent']} !important; font-weight: 700; }}
[data-testid^="stBaseButton-secondary"] p {{ color: {C['accent']}; font-weight: 700; }}
[data-testid^="stBaseButton-secondary"]:hover:not(:disabled) {{ background: {C['accent']} !important; }}
[data-testid^="stBaseButton-secondary"]:hover:not(:disabled) p {{ color: {C['white']}; }}
[data-testid^="stBaseButton-secondary"]:disabled {{ border-color: {C['line']} !important; opacity: .6; }}
[data-testid^="stBaseButton-secondary"]:disabled p {{ color: {C['muted']}; }}

/* ---------- segmented control (มีราง) ---------- */
[data-testid="stButtonGroup"]:has([data-testid^="stBaseButton-segmented_control"]) > div {{ gap: 4px; background: {C['white']};
    border-radius: 999px; padding: 5px; width: fit-content; max-width: 100%; flex-wrap: wrap; box-shadow: {CARD_SHADOW}; }}
[data-testid^="stBaseButton-segmented_control"] {{ border: 0 !important; border-radius: 50px !important; min-height: 38px;
    padding: 0 20px; background: transparent; }}
[data-testid^="stBaseButton-segmented_control"] p {{ font-size: 15px; font-weight: 700; color: {C['muted']}; white-space: nowrap; }}
[data-testid="stBaseButton-segmented_control"]:hover {{ background: {C['mint']} !important; }}
[data-testid="stBaseButton-segmented_control"]:hover p {{ color: {C['accent']}; }}
[data-testid="stBaseButton-segmented_controlActive"],
[data-testid="stBaseButton-segmented_controlActive"]:hover {{ background: {C['accent']} !important; }}
[data-testid="stBaseButton-segmented_controlActive"] p,
[data-testid="stBaseButton-segmented_controlActive"]:hover p {{ color: {C['white']} !important; }}
.st-key-viewbar {{ margin-bottom: 8px; }}

/* ---------- pills (เลือกได้หลายอัน: แต่ละอันเป็นชิปแยก ไม่มีราง) ---------- */
[data-testid="stButtonGroup"]:has([data-testid^="stBaseButton-pills"]) > div {{ gap: 8px; flex-wrap: wrap; }}
[data-testid^="stBaseButton-pills"] {{ border-radius: 999px !important; min-height: 34px; padding: 0 14px;
    border: 1px solid {C['line']} !important; background: {C['white']} !important; }}
[data-testid^="stBaseButton-pills"] p {{ font-size: 14px; font-weight: 700; color: {C['muted']}; white-space: nowrap; }}
[data-testid="stBaseButton-pills"]:hover {{ border-color: {C['accent']} !important; }}
[data-testid="stBaseButton-pills"]:hover p {{ color: {C['accent']}; }}
[data-testid="stBaseButton-pillsActive"] {{ background: {C['accent']} !important; border-color: {C['accent']} !important; }}
[data-testid="stBaseButton-pillsActive"] p {{ color: {C['white']} !important; }}

/* ---------- inputs ---------- */
[data-testid="stWidgetLabel"] p {{ font-size: 13px; font-weight: 800; color: {C['charcoal']}; }}
[data-baseweb="select"] > div, [data-baseweb="input"] {{ border-radius: 999px !important; background: {C['white']} !important;
    border: 1px solid {C['line']} !important; transition: border-color .2s ease, box-shadow .2s ease; }}
[data-baseweb="select"] > div:hover, [data-baseweb="input"]:hover {{ border-color: {C['accent']} !important; }}
[data-baseweb="select"] > div:focus-within, [data-baseweb="input"]:focus-within {{ border-color: {C['accent']} !important;
    box-shadow: 0 0 0 3px rgba(0,117,74,.15); }}
[data-baseweb="tag"] {{ border-radius: 999px !important; background: {C['accent']} !important; }}
[data-baseweb="popover"] li[role="option"]:hover, [data-baseweb="popover"] li[aria-selected="true"] {{ background: {C['mint']} !important; }}
[data-testid="stSliderThumbValue"] {{ font-family: {FONT} !important; color: {C['brand']}; font-weight: 800; }}
[data-testid="stSliderTickBar"] {{ display: none; }}  /* ค่า min/max ซ้ำกับค่าบนหัวแถบ */
[data-testid="stSlider"] [role="slider"] {{ box-shadow: 0 0 0 4px rgba(0,117,74,.15); transition: box-shadow .2s ease; }}
[data-testid="stSlider"] [role="slider"]:hover {{ box-shadow: 0 0 0 7px rgba(0,117,74,.18); }}
[data-testid="stCheckbox"] label:hover p {{ color: {C['accent']}; }}
[data-testid="stDataFrame"] {{ border-radius: 12px; overflow: hidden; box-shadow: inset 0 0 0 1px {C['line']}; }}

/* ---------- pagination: เลขหน้าเป็นแคปซูลเรียงกลาง ---------- */
[class*="st-key-pagernums-"] [data-testid="stHorizontalBlock"] {{ justify-content: center; align-items: center; gap: 6px; flex-wrap: wrap; }}
[class*="st-key-pagernums-"] [data-testid="stColumn"] {{ flex: 0 0 auto !important; width: auto !important;
    min-width: max-content !important; }}
[class*="st-key-pagernums-"] [data-testid="stColumn"] * {{ width: auto !important; }}
[class*="st-key-pagernums-"] button {{ min-width: 40px; min-height: 40px; padding: 0 12px !important; }}
[class*="st-key-pagernums-"] button p {{ white-space: nowrap; font-weight: 700; }}
[class*="st-key-pagernums-"] [data-testid="stBaseButton-primary"] {{ border-radius: 50px !important; background: {C['accent']} !important;
    border: 1px solid {C['accent']} !important; }}
[class*="st-key-pagernums-"] [data-testid="stBaseButton-primary"] p {{ color: {C['white']}; font-weight: 800; }}
.pager-gap {{ color: {C['muted']}; padding: 0 2px; }}
.pager-info {{ font-size: 13.5px; color: {C['muted']}; }}
.pager-info b {{ color: {C['house']}; font-weight: 800; }}
[class*="st-key-pagerfoot-"] [data-testid="stHorizontalBlock"] {{ align-items: center; }}
[class*="st-key-pagerfoot-"] [data-baseweb="select"] > div {{ min-height: 34px; }}

/* ---------- scrollbars (ส่วนที่ยาวเกินกรอบ) ---------- */
* {{ scrollbar-width: thin; scrollbar-color: {C['taupe']} transparent; }}
::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: {C['taupe']}; border-radius: 999px; border: 2px solid transparent;
    background-clip: content-box; }}
::-webkit-scrollbar-thumb:hover {{ background-color: {C['accent2']}; }}

/* ---------- footer ---------- */
.footer {{ background: {C['house']}; color: {C['white']}; border-radius: 12px; padding: 40px 44px; margin-top: 56px; }}
.footer h3 {{ color: {C['accent3']}; font-size: 22px; font-weight: 800; margin: 0 0 22px; padding: 0; }}
.footer .cols {{ display: flex; flex-wrap: wrap; gap: 48px; font-size: 14px; line-height: 1.9;
                color: rgba(255,255,255,.70); }}
.footer .cols b {{ display: block; text-transform: uppercase; letter-spacing: .1em; font-size: 12px; font-weight: 800;
                  color: {C['white']}; margin-bottom: 4px; }}
.footer a {{ color: {C['white']}; text-decoration: none; border-bottom: 1px solid rgba(255,255,255,.3);
            transition: border-color .2s ease, color .2s ease; }}
.footer a:hover {{ color: {C['accent3']}; border-color: {C['accent3']}; }}

/* ---------- ปุ่มลอยกลับขึ้นบน (Frap) ---------- */
.frap {{ position: fixed; right: 28px; bottom: 28px; z-index: 1000; width: 56px; height: 56px; border-radius: 50%;
        background: {C['accent']}; color: {C['white']} !important; display: flex; align-items: center;
        justify-content: center; font-size: 22px; font-weight: 800; text-decoration: none !important;
        box-shadow: 0 0 6px rgba(0,0,0,.24), 0 8px 12px rgba(0,0,0,.14); transition: all .2s ease; }}
.frap:hover {{ background: {C['brand']}; transform: translateY(-2px); }}
.frap:active {{ transform: scale(.95); box-shadow: 0 0 6px rgba(0,0,0,.24), 0 8px 12px rgba(0,0,0,0); }}

@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ transition: none !important; animation: none !important; }}
}}
</style>
"""

FOOTER = """
<div class="footer">
  <h3>ข้อมูลแผ่นดินไหวจากสามหน่วยงาน รวมไว้ในที่เดียว</h3>
  <div class="cols">
    <div><b>แหล่งข้อมูล</b>
      <a href="https://earthquake.tmd.go.th/inside.html" target="_blank">กรมอุตุนิยมวิทยา ↗</a><br>
      <a href="https://earthquake.usgs.gov/" target="_blank">USGS ↗</a><br>
      <a href="https://www.seismicportal.eu/" target="_blank">EMSC ↗</a></div>
    <div><b>Pipeline</b>Apache Airflow → PostgreSQL → Streamlit<br>อัปเดตทุก 30 นาที</div>
    <div><b>รายวิชา</b>02739452 แพลตฟอร์มข้อมูลขนาดใหญ่<br>และการวิเคราะห์</div>
  </div>
</div>
<a class="frap" href="#top" title="กลับขึ้นด้านบน">↑</a>
"""

def apply_theme():
    st.markdown(CSS, unsafe_allow_html=True)


LOGO_FILE = Path(__file__).parent / "static" / "logo.png"


@st.cache_resource
def logo_data_uri() -> str:
    return "data:image/png;base64," + base64.b64encode(LOGO_FILE.read_bytes()).decode()


def top_nav(pages: list, current, freshness: str = ""):
    """แถบบนเต็มความกว้าง: โลโก้ + เวลาอัปเดตล่าสุดซ้าย, เมนูหน้าขวา (หน้าปัจจุบันเป็นแคปซูลสีเขียว)"""
    with st.container(key="topnav"):
        cols = st.columns([4.2] + [1.25] * (len(pages) + 1), vertical_alignment="center")
        cols[0].markdown(f"<div class='brand'><img class='logo' src='{logo_data_uri()}' alt=''><span class='text'>"
                         "<strong>Quake Monitor</strong>"
                         f"<small>{escape(freshness) or 'แผ่นดินไหวในไทยและประเทศเพื่อนบ้าน'}</small></span></div>",
                         unsafe_allow_html=True)
        for col, page in zip(cols[1:], pages):
            active = page.title == current.title
            with col.container(key=f"nav-{'active' if active else 'idle'}-{page.url_path or 'home'}"):
                st.page_link(page, label=page.title)
        with cols[-1].container(key="nav-airflow"):
            st.page_link("http://localhost:8080", label="Airflow ↗")


def page_header(eyebrow: str, title: str, lede: str = "", meta: list[str] | None = None):
    """meta: ข้อความสั้นใน pill ใช้ <b> เน้นตัวเลขได้"""
    meta_html = "".join(f"<span>{m}</span>" for m in (meta or []))
    st.markdown(
        f"<div id='top'></div><div class='eyebrow'>{escape(eyebrow)}</div>"
        f"<div class='page-title'>{escape(title)}</div>"
        + (f"<p class='page-lede'>{lede}</p>" if lede else "")
        + (f"<div class='meta'>{meta_html}</div>" if meta_html else ""),
        unsafe_allow_html=True)


def _section_html(title: str, desc: str, kicker: str) -> str:
    return ("<div class='section'>" + (f"<div class='kicker'>{escape(kicker)}</div>" if kicker else "")
            + f"<h2>{escape(title)}</h2>" + (f"<p>{desc}</p>" if desc else "") + "</div>")


def section(title: str, desc: str = "", kicker: str = "", controls: bool = False):
    """หัวข้อส่วน: kicker + H2 + คำอธิบาย ถ้า controls=True จะคืนคอลัมน์ขวาไว้วางตัวควบคุม (ค้นหา/ตัวเลือก)"""
    if not controls:
        st.markdown(_section_html(title, desc, kicker), unsafe_allow_html=True)
        return None
    key = "sechead-" + hashlib.md5(title.encode()).hexdigest()[:8]
    with st.container(key=key):
        left, right = st.columns([3, 2], vertical_alignment="bottom")
        left.markdown(_section_html(title, desc, kicker), unsafe_allow_html=True)
    return right


def stat_strip(items: list[dict]):
    """แถบตัวเลขสำคัญหลายช่องต่อกันเป็นแถบเดียว: [{"label", "value", "unit"?, "sub"?}]"""
    cells = []
    for it in items:
        unit = f"<small>{escape(str(it['unit']))}</small>" if it.get("unit") else ""
        sub = f"<div class='sub' title='{escape(str(it['sub']))}'>{escape(str(it['sub']))}</div>" if it.get("sub") else ""
        cells.append(f"<div class='cell'><div class='label'>{escape(it['label'])}</div>"
                     f"<div class='value'>{escape(str(it['value']))}{unit}</div>{sub}</div>")
    st.markdown(f"<div class='stat-strip'>{''.join(cells)}</div>", unsafe_allow_html=True)


def flow(steps: list[tuple[str, str]]):
    """ขั้นตอน pipeline เรียงเป็นแถวมีลูกศร: [(ชื่อขั้น, คำอธิบาย)]"""
    items = "".join(f"<li><span class='n'>{i}</span><b>{escape(t)}</b><span>{d}</span></li>"
                    for i, (t, d) in enumerate(steps, 1))
    st.markdown(f"<ol class='flow'>{items}</ol>", unsafe_allow_html=True)


def note(html: str):
    st.markdown(f"<p class='note'>{html}</p>", unsafe_allow_html=True)


def kpis(items: list[dict]):
    """items: [{"label", "value", "unit"?, "sub"?, "accent"?}]"""
    cards = []
    for it in items:
        unit = f"<small>{escape(str(it['unit']))}</small>" if it.get("unit") else ""
        sub = f"<div class='sub' title='{escape(str(it['sub']))}'>{escape(str(it['sub']))}</div>" if it.get("sub") else ""
        cards.append(f"<div class='kpi{' accent' if it.get('accent') else ''}'>"
                     f"<div class='label'>{escape(it['label'])}</div>"
                     f"<div class='value'>{escape(str(it['value']))}{unit}</div>{sub}</div>")
    st.markdown(f"<div class='kpis'>{''.join(cards)}</div>", unsafe_allow_html=True)


@contextmanager
def card(title: str, desc: str = ""):
    key = "card-" + hashlib.md5(title.encode()).hexdigest()[:8]
    with st.container(border=True, key=key):
        st.markdown(f"<div class='card-head'><h4>{escape(title)}</h4>"
                    + (f"<p>{desc}</p>" if desc else "") + "</div>", unsafe_allow_html=True)
        yield


def card_note(html: str):
    st.markdown(f"<div class='card-note'>{html}</div>", unsafe_allow_html=True)


def badge(status: str) -> str:
    kind = {"success": "ok", "SUCCESS": "ok", "PARTIAL": "warn", "QUALITY_FAILED": "warn"}.get(status, "fail")
    label = {"success": "สำเร็จ", "failed": "ล้มเหลว", "SUCCESS": "สำเร็จ", "PARTIAL": "บางแหล่งล่ม",
             "QUALITY_FAILED": "คุณภาพไม่ผ่าน", "FAILED": "ล้มเหลว"}.get(status, status)
    return f"<span class='badge {kind}'>{label}</span>"


def paged_dataframe(df, key: str, sizes=(10, 25, 50), max_height: int = 460, selectable: bool = False, **kwargs):
    """ตารางแบบแบ่งหน้า: แสดงเฉพาะหน้าปัจจุบัน และมีแถบเปลี่ยนหน้า/จำนวนแถวต่อหน้าไว้ใต้ตาราง

    selectable=True ให้คลิกเลือกแถวได้ และคืนแถวที่เลือก (pd.Series) หรือ None

    ตารางมีความสูงไม่เกิน max_height ถ้าแถวในหน้ามากกว่านั้นจะเลื่อนดูในตารางได้
    """
    total = len(df)
    size_key, page_key, total_key = f"{key}_size", f"{key}_page", f"{key}_total"
    size = st.session_state.get(size_key, sizes[0])
    pages = max(1, math.ceil(total / size))
    # จำนวนแถวเปลี่ยน (เช่นเปลี่ยนตัวกรอง) ให้กลับไปหน้าแรก
    if st.session_state.get(total_key) != total:
        st.session_state[total_key] = total
        st.session_state[page_key] = 1
    page = min(max(st.session_state.get(page_key, 1), 1), pages)
    st.session_state[page_key] = page

    start = (page - 1) * size
    chunk = df.iloc[start:start + size]
    if selectable:
        kwargs.update(on_select="rerun", selection_mode="single-row", key=f"{key}_table_{page}_{size}")
    event = st.dataframe(chunk, height=min(max_height, 38 + 35 * max(len(chunk), 1)),
                         use_container_width=True, hide_index=True, **kwargs)
    rows = event.selection.rows if selectable else []
    selected = chunk.iloc[rows[0]] if rows else None

    def go(target):
        st.session_state[page_key] = target

    # เลขหน้าแบบ ‹ 1 … 4 5 6 … 23 › เรียงกลาง (แบบเว็บค่าครองชีพ)
    shown_pages = sorted({1, pages, page - 1, page, page + 1} & set(range(1, pages + 1)))
    items, prev_n = [], 0
    for n in shown_pages:
        if n - prev_n > 1:
            items.append(None)
        items.append(n)
        prev_n = n
    if pages > 1:
        with st.container(key=f"pagernums-{key}"):
            cols = st.columns(len(items) + 2, vertical_alignment="center")
            cols[0].button("‹", key=f"{key}_prev", on_click=go, args=(page - 1,), disabled=page <= 1)
            for col, n in zip(cols[1:-1], items):
                if n is None:
                    col.markdown("<span class='pager-gap'>…</span>", unsafe_allow_html=True)
                else:
                    col.button(str(n), key=f"{key}_p{n}", on_click=go, args=(n,),
                               type="primary" if n == page else "secondary")
            cols[-1].button("›", key=f"{key}_next", on_click=go, args=(page + 1,), disabled=page >= pages)

    with st.container(key=f"pagerfoot-{key}"):
        info, per = st.columns([4, 1.3], vertical_alignment="center")
        shown = f"<b>{start + 1:,}–{start + len(chunk):,}</b> จาก <b>{total:,}</b> รายการ" if total else "ไม่มีรายการ"
        info.markdown(f"<div class='pager-info'>แสดง {shown}</div>", unsafe_allow_html=True)
        per.selectbox("แถวต่อหน้า", sizes, key=size_key, label_visibility="collapsed",
                      format_func=lambda n: f"{n} แถว / หน้า",
                      on_change=lambda: st.session_state.update({page_key: 1}))
    return selected


def footer():
    st.markdown(FOOTER, unsafe_allow_html=True)


def chart(fig, **kwargs):
    # theme=None เพื่อใช้ template ของเราแทนธีมเริ่มต้นของ Streamlit; ซ่อนแถบเครื่องมือให้หน้าเรียบ
    fig.update_layout(template="plotly_white+quake", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True, theme=None,
                    config={"displayModeBar": False, "scrollZoom": False}, **kwargs)
