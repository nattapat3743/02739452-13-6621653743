"""หน้าภาพรวม: hero + เหตุการณ์ล่าสุด, แถบตัวเลข, ตัวกรอง, แผนที่คู่ตารางอันดับ, กราฟ และตารางเหตุการณ์"""
from datetime import timedelta
from html import escape

import pandas as pd
import plotly.express as px
import streamlit as st

from db import query, tables_ready
from geo import PLATES_CREDIT, SEVERITY_LABELS, add_plates, haversine_km, severity, severity_chip, style_geo
from theme import (C, MAG_SCALE, SOURCE_COLORS, card, chart, note, page_header, paged_dataframe,
                   section, stat_strip)
from wave import mmss, wave_map

# จับคำในชื่อบริเวณของแต่ละแหล่ง (ไทย/อังกฤษ) ให้เป็นชื่อประเทศเดียวกัน
COUNTRIES = [
    ("ไทย", ("thailand", "ไทย", "จ.", "อ.")), ("เมียนมา", ("myanmar", "เมียนมา", "burma")),
    ("ลาว", ("laos", "ลาว")), ("จีน", ("china", "จีน", "yunnan")), ("เวียดนาม", ("vietnam", "เวียดนาม")),
    ("กัมพูชา", ("cambodia", "กัมพูชา")), ("อินโดนีเซีย", ("indonesia", "sumatra", "อินโดนีเซีย")),
    ("อินเดีย (อันดามัน-นิโคบาร์)", ("andaman", "nicobar", "อันดามัน")), ("อินเดีย", ("india", "อินเดีย")),
    ("บังกลาเทศ", ("bangladesh", "บังกลาเทศ")), ("มาเลเซีย", ("malaysia", "มาเลเซีย")),
]


def country(place: str) -> str:
    text = (place or "").lower()
    for name, keys in COUNTRIES:
        if any(k in text for k in keys):
            return name
    return "อื่น ๆ / ทะเล"


def ago(ts: pd.Timestamp) -> str:
    minutes = int((pd.Timestamp.now(tz="UTC") - ts).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} นาทีที่แล้ว"
    if minutes < 60 * 24:
        return f"{minutes // 60} ชั่วโมงที่แล้ว"
    return f"{minutes // (60 * 24)} วันที่แล้ว"


if not tables_ready():
    page_header("Earthquake monitor", "แผ่นดินไหวในไทยและประเทศเพื่อนบ้าน")
    st.warning("ยังไม่มีข้อมูล: รอ DAG `earthquake_pipeline` ใน Airflow รันครั้งแรกก่อน (http://localhost:8080)")
    st.stop()

events = query("SELECT * FROM earthquakes ORDER BY event_time_utc DESC")
if events.empty:
    st.info("ตาราง earthquakes ยังว่างอยู่")
    st.stop()

events["event_time_utc"] = pd.to_datetime(events["event_time_utc"], utc=True)
events["event_time_th"] = events["event_time_utc"].dt.tz_convert("Asia/Bangkok")
for c in ("magnitude", "mag_min", "mag_max", "depth_km"):
    events[c] = events[c].astype(float)
events["country"] = events["place"].map(country)
events["severity"] = events["magnitude"].map(lambda m: severity(m)[0])
now = pd.Timestamp.now(tz="UTC")

# ---------------------------------------------------------------- hero
recent = events[events["event_time_utc"] >= now - timedelta(days=30)]
top = recent.loc[recent["magnitude"].idxmax()] if len(recent) else events.loc[events["magnitude"].idxmax()]
by_country = recent["country"].value_counts()
last24 = int((events["event_time_utc"] >= now - timedelta(hours=24)).sum())
latest = events.iloc[0]

st.markdown("<div id='top'></div>", unsafe_allow_html=True)
hero_left, hero_right = st.columns([7, 5], gap="large", vertical_alignment="center")
with hero_left:
    st.markdown(
        "<div class='hero-kicker'>30 วันล่าสุด · ไทยและประเทศเพื่อนบ้าน</div>"
        f"<div class='hero-title'>เกิดแผ่นดินไหว <span class='num'>{len(recent):,}</span> ครั้ง<br>"
        f"ใหญ่สุดขนาด <span class='num'>{top['magnitude']:.1f}</span></div>"
        f"<p class='hero-lede'>เกิดบ่อยที่สุดใน<b>{escape(by_country.index[0]) if len(by_country) else '-'}</b> "
        f"({by_country.iloc[0] if len(by_country) else 0:,} ครั้ง) · ครั้งใหญ่สุดอยู่ที่ "
        f"<b>{escape(str(top['place']))}</b> · ใน 24 ชั่วโมงล่าสุดเกิด <b>{last24} ครั้ง</b></p>"
        "<div class='hero-mini'>จำนวนครั้งต่อวัน</div>",
        unsafe_allow_html=True)
    today = now.tz_convert("Asia/Bangkok").date()
    spark = (recent.assign(day=recent["event_time_th"].dt.date).groupby("day").size()
             .reindex(pd.date_range(today - timedelta(days=29), today).date, fill_value=0))
    fig = px.bar(x=spark.index, y=spark.values, height=120, labels={"x": "", "y": ""})
    fig.update_traces(marker_color=C["accent"], hovertemplate="%{x|%d/%m}: %{y} ครั้ง<extra></extra>")
    fig.update_layout(bargap=0.3, yaxis=dict(showgrid=False, showticklabels=False),
                      xaxis=dict(showgrid=False, tickformat="%d/%m", nticks=6))
    chart(fig)

with hero_right:
    chips = "".join(f"<span>{s}</span>" for s in latest["sources"].split(","))
    st.markdown(
        "<div class='feature'><div class='kicker'>เหตุการณ์ล่าสุด · " + ago(latest["event_time_utc"]) + "</div>"
        f"<div class='mag'>{latest['magnitude']:.1f}<small>แมกนิจูด</small></div>"
        f"{severity_chip(latest['magnitude'])}"
        f"<div class='place'>{escape(str(latest['place']))}</div>"
        "<div class='rows'>"
        f"<span>เวลา</span><b>{latest['event_time_th']:%d/%m/%Y %H:%M} น.</b>"
        f"<span>ความลึก</span><b>{latest['depth_km']:.0f} กม.</b>"
        f"<span>พิกัด</span><b>{latest['latitude']:.2f}°N, {latest['longitude']:.2f}°E</b>"
        f"<span>รายงานโดย</span><b>{latest['n_sources']} หน่วยงาน</b>"
        f"</div><div class='chips'>{chips}</div></div>",
        unsafe_allow_html=True)

stat_strip([
    {"label": "เหตุการณ์ในฐานข้อมูล", "value": f"{len(events):,}", "unit": "ครั้ง", "sub": "หลังตัดซ้ำข้ามแหล่ง"},
    {"label": "ขนาดเฉลี่ย (30 วัน)", "value": f"{recent['magnitude'].mean():.2f}" if len(recent) else "-"},
    {"label": "ความลึกเฉลี่ย (30 วัน)", "value": f"{recent['depth_km'].mean():.0f}" if len(recent) else "-",
     "unit": "กม."},
    {"label": "ยืนยันจาก 2 แหล่งขึ้นไป", "value": f"{(events['n_sources'] >= 2).mean():.0%}",
     "sub": "รายงานตรงกันหลายหน่วยงาน"},
])

# ---------------------------------------------------------------- filters
section("สำรวจข้อมูล", "เลือกช่วงเวลา ขนาด และแหล่ง แผนที่ กราฟ และตารางด้านล่างจะเปลี่ยนตาม", kicker="ตัวกรอง")
min_d = events["event_time_th"].min().date()
max_d = events["event_time_th"].max().date()
f1, f3, f4 = st.columns([1.1, 1.5, 0.8], gap="medium")
d_range = f1.date_input("ช่วงวันที่ (เวลาไทย)", (max(min_d, max_d - timedelta(days=30)), max_d),
                        min_value=min_d, max_value=max_d)
sources = f3.multiselect("แหล่งข้อมูล", ["TMD", "USGS", "EMSC"], ["TMD", "USGS", "EMSC"])
min_sources = f4.selectbox("ยืนยันจากอย่างน้อย", [1, 2, 3], format_func=lambda n: f"{n} แหล่ง")
levels = st.pills("ระดับความรุนแรง (กดเพื่อเลือก/ไม่เลือก)", SEVERITY_LABELS, selection_mode="multi",
                  default=SEVERITY_LABELS, help="เล็กมาก < 3 · รู้สึกได้ 3–4 · ปานกลาง 4–5 · แรง 5–6 · รุนแรง 6 ขึ้นไป")

start, end = (d_range if isinstance(d_range, tuple) and len(d_range) == 2 else (min_d, max_d))
df = events[
    events["event_time_th"].dt.date.between(start, end)
    & events["severity"].isin(levels or SEVERITY_LABELS)
    & events["n_sources"].ge(min_sources)
    & events["sources"].apply(lambda s: any(src in s.split(",") for src in sources))
]
if df.empty:
    st.info("ไม่มีข้อมูลตามตัวกรองที่เลือก")
    st.stop()

# ---------------------------------------------------------------- map + side
section("เกิดที่ไหน", f"{len(df):,} เหตุการณ์ตามตัวกรอง · ขนาดและสีของวงตามขนาดแผ่นดินไหว", kicker="แผนที่")
map_col, side_col = st.columns([7, 5], gap="medium")
with map_col, card("แผนที่ตำแหน่งแผ่นดินไหว",
                   "เส้นแดงคือเขตมุดตัวของแผ่นเปลือกโลก ซึ่งแผ่นดินไหวส่วนใหญ่เกิดตามแนวนี้ · ชี้ที่วงเพื่อดูรายละเอียด · ลากเพื่อเลื่อนแผนที่"):
    timelapse = st.toggle("▶ เล่นย้อนหลังทีละวัน")
    mdf = df.sort_values("event_time_utc").assign(
        day=lambda d: d["event_time_th"].dt.strftime("%Y-%m-%d"),
        size=lambda d: d["magnitude"].clip(lower=0.5) ** 2)
    fig = px.scatter_geo(
        mdf, lat="latitude", lon="longitude", size="size", color="magnitude",
        color_continuous_scale=MAG_SCALE, range_color=(mdf["magnitude"].min(), mdf["magnitude"].max()),
        size_max=20, hover_name="place",
        hover_data={"event_time_th": True, "magnitude": True, "depth_km": True, "sources": True,
                    "latitude": False, "longitude": False, "size": False, "day": False},
        labels={"magnitude": "ขนาด", "event_time_th": "เวลา", "depth_km": "ลึก (กม.)", "sources": "แหล่ง"},
        animation_frame="day" if timelapse else None, height=600)
    fig.update_traces(marker=dict(line=dict(color=C["white"], width=0.8), opacity=0.9), selector=dict(type="scattergeo"))
    style_geo(fig, (-1, 31), (80, 118))
    fig.update_layout(coloraxis_colorbar=dict(
        title=dict(text="ขนาด", side="top"), thickness=10, len=0.32, x=0.985, xanchor="right", y=0.96,
        yanchor="top", bgcolor="rgba(255,255,255,.88)", outlinewidth=0, xpad=12, ypad=12))
    if timelapse:
        fig.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"] = 400
    add_plates(fig)
    chart(fig)
    st.caption(PLATES_CREDIT)

with side_col:
    with card("เกิดบ่อยที่ไหน", "จำนวนครั้งแยกตามประเทศ/พื้นที่"):
        rank = (df.groupby("country").agg(ครั้ง=("event_key", "size"), ขนาดสูงสุด=("magnitude", "max"))
                .sort_values("ครั้ง", ascending=False).reset_index().rename(columns={"country": "ประเทศ/พื้นที่"}))
        st.dataframe(rank, hide_index=True, use_container_width=True, height=min(300, 38 + 35 * len(rank)),
                     column_config={
                         "ครั้ง": st.column_config.ProgressColumn(
                             "ครั้ง", min_value=0, max_value=int(rank["ครั้ง"].max()), format="%d"),
                         "ขนาดสูงสุด": st.column_config.NumberColumn(format="%.1f")})
    with card("5 ครั้งที่ใหญ่ที่สุด", "ตามตัวกรองที่เลือก"):
        big = df.nlargest(5, "magnitude")[["magnitude", "place", "event_time_th"]]
        st.dataframe(big, hide_index=True, use_container_width=True,
                     column_config={"magnitude": st.column_config.NumberColumn("ขนาด", format="%.1f"),
                                    "place": st.column_config.TextColumn("บริเวณ", width="medium"),
                                    "event_time_th": st.column_config.DatetimeColumn("เวลา", format="DD/MM HH:mm")})

# ---------------------------------------------------------------- trends
section("เมื่อไร และใครรายงาน", "จำนวนครั้งในแต่ละวัน และขนาดที่แต่ละหน่วยงานรายงานสำหรับเหตุการณ์เดียวกัน",
        kicker="แนวโน้ม")
left, right = st.columns(2, gap="medium")
with left, card("จำนวนเหตุการณ์รายวัน", "แยกตามจำนวนหน่วยงานที่รายงาน"):
    daily = (df.assign(day=df["event_time_th"].dt.date,
                       confirmed=df["n_sources"].map(lambda n: f"{n} แหล่ง"))
             .groupby(["day", "confirmed"]).size().reset_index(name="count"))
    fig = px.bar(daily, x="day", y="count", color="confirmed", height=300,
                 color_discrete_map={"1 แหล่ง": C["taupe"], "2 แหล่ง": C["accent2"], "3 แหล่ง": C["accent"]},
                 labels={"day": "", "count": "", "confirmed": ""})
    fig.update_layout(legend=dict(orientation="h", y=1.12, x=0), bargap=0.25, xaxis_tickformat="%d/%m")
    chart(fig)

with right, card("ขนาดที่แต่ละแหล่งรายงาน", "เฉพาะเหตุการณ์ที่รายงานตรงกันตั้งแต่ 2 แหล่ง"):
    keys = df.loc[df["n_sources"] >= 2, "event_key"].tolist()
    if keys:
        raw = query("""SELECT event_key, source, magnitude FROM earthquakes_raw
                       WHERE event_key = ANY(:keys)""", keys=keys)
        raw["magnitude"] = raw["magnitude"].astype(float)
        fig = px.box(raw, x="source", y="magnitude", color="source", points="all", height=300,
                     category_orders={"source": ["TMD", "USGS", "EMSC"]},
                     color_discrete_map=SOURCE_COLORS, labels={"source": "", "magnitude": "ขนาด"})
        fig.update_traces(marker=dict(size=5, opacity=0.7), jitter=0.4, pointpos=-1.6)
        fig.update_layout(showlegend=False)
        chart(fig)
    else:
        st.caption("ยังไม่มีเหตุการณ์ที่รายงานตรงกันหลายแหล่งในช่วงที่เลือก")

# ---------------------------------------------------------------- table
search_col = section("รายการเหตุการณ์", "เรียงจากล่าสุด · เวลาเป็นเวลาประเทศไทย", kicker="ข้อมูลทั้งหมด",
                     controls=True)
q = search_col.text_input("ค้นหาบริเวณ", placeholder="ค้นหาบริเวณ เช่น Myanmar, เมียนมา, Sumatra",
                          label_visibility="collapsed")
table = df[df["place"].str.contains(q, case=False, na=False, regex=False)] if q else df
with card(f"{len(table):,} เหตุการณ์", "ขนาดต่ำสุด–สูงสุด คือช่วงที่หน่วยงานต่าง ๆ รายงานไม่ตรงกัน"):
    st.markdown("<div class='hint'><b>คลิกแถว</b> เพื่อดูว่าแต่ละหน่วยงานรายงานเหตุการณ์นั้นอย่างไร</div>",
                unsafe_allow_html=True)
    selected = paged_dataframe(
        table[["event_key", "event_time_th", "magnitude", "severity", "mag_min", "mag_max", "depth_km", "place",
               "country", "sources", "n_sources"]],
        column_order=["event_time_th", "magnitude", "severity", "mag_min", "mag_max", "depth_km", "place",
                      "country", "sources", "n_sources"],
        selectable=True,
        column_config={
            "severity": "ระดับ",
            "event_time_th": st.column_config.DatetimeColumn("เวลา", format="DD/MM/YYYY HH:mm"),
            "magnitude": st.column_config.NumberColumn("ขนาด", format="%.1f"),
            "mag_min": st.column_config.NumberColumn("ต่ำสุด", format="%.1f", width="small"),
            "mag_max": st.column_config.NumberColumn("สูงสุด", format="%.1f", width="small"),
            "depth_km": st.column_config.NumberColumn("ลึก (กม.)", format="%.0f", width="small"),
            "place": st.column_config.TextColumn("บริเวณ", width="medium"),
            "country": "ประเทศ",
            "sources": "แหล่ง",
            "n_sources": st.column_config.ProgressColumn("ยืนยัน", min_value=0, max_value=3, format="%d",
                                                         width="small"),
        },
        key="events", sizes=(10, 25, 50, 100))

# ---------------------------------------------------------------- compare sources
SOURCE_NAMES = {"TMD": "กรมอุตุนิยมวิทยา", "USGS": "USGS", "EMSC": "EMSC"}
section("แต่ละหน่วยงานรายงานอย่างไร",
        "เหตุการณ์เดียวกันที่ถูกรวมจากหลายแหล่ง: เวลา ขนาด และตำแหน่งที่แต่ละหน่วยงานรายงานต่างกันแค่ไหน",
        kicker="เทียบ 3 แหล่ง")
is_default = selected is None
if is_default:
    # ยังไม่ได้คลิก: แสดงเหตุการณ์ล่าสุดที่หลายหน่วยงานรายงาน โดยเลือกที่มี TMD (แหล่ง scraping) ก่อน
    pool = table if (table["n_sources"] >= 2).any() else df
    ev = (pool.assign(has_tmd=pool["sources"].str.contains("TMD"))
          .sort_values(["n_sources", "has_tmd", "event_time_utc"], ascending=False).iloc[0])
else:
    ev = events.set_index("event_key").loc[selected["event_key"]]
    ev["event_key"] = selected["event_key"]
    ev = ev.copy()

reports = query("""SELECT source, source_event_id, event_time_utc, magnitude, latitude, longitude, depth_km, place
                   FROM earthquakes_raw WHERE event_key = :k""", k=ev["event_key"])
reports["event_time_utc"] = pd.to_datetime(reports["event_time_utc"], utc=True)
for c in ("magnitude", "latitude", "longitude", "depth_km"):
    reports[c] = reports[c].astype(float)
ref = reports[reports["source"] == ev["primary_source"]].iloc[0] if len(reports) else None

cmp_col, mini_col = st.columns([7, 5], gap="medium")
with cmp_col, card(str(ev["place"]),
                   f"{ev['event_time_th']:%d/%m/%Y %H:%M} น. · ขนาด {ev['magnitude']:.1f} {severity_chip(ev['magnitude'])}"):
    if is_default:
        st.markdown("<div class='hint'>แสดงเหตุการณ์ล่าสุดที่หลายหน่วยงานรายงาน · "
                    "<b>คลิกแถวในตารางด้านบน</b> เพื่อเปลี่ยนเหตุการณ์</div>", unsafe_allow_html=True)
    # ตารางเทียบ: แถว = หัวข้อ, คอลัมน์ = แหล่ง
    cols, cells = [], {k: [] for k in ("ขนาด", "เวลา (ไทย)", "ต่างจากตัวแทน", "พิกัด", "ห่างจากตัวแทน",
                                        "ความลึก", "รหัสของแหล่ง")}
    for src in ("TMD", "USGS", "EMSC"):
        r = reports[reports["source"] == src]
        is_ref = src == ev["primary_source"]
        tag = "<span class='ref'>ตัวแทน</span>" if is_ref else ""
        cols.append(f"<th style='--c:{SOURCE_COLORS[src]}'><i></i>{SOURCE_NAMES[src]}{tag}</th>")
        if r.empty:
            for k in cells:
                cells[k].append("<td class='na'>ไม่ได้รายงาน</td>" if k == "ขนาด" else "<td class='na'>–</td>")
            continue
        r = r.iloc[0]
        dt = (r["event_time_utc"] - ref["event_time_utc"]).total_seconds()
        dist = haversine_km(ref["latitude"], ref["longitude"], r["latitude"], r["longitude"])
        cells["ขนาด"].append(f"<td class='big'>{r['magnitude']:.1f}</td>")
        cells["เวลา (ไทย)"].append(f"<td>{r['event_time_utc'].tz_convert('Asia/Bangkok'):%H:%M:%S}</td>")
        cells["ต่างจากตัวแทน"].append(f"<td>{'–' if is_ref else f'{dt:+.0f} วินาที'}</td>")
        cells["พิกัด"].append(f"<td>{r['latitude']:.2f}, {r['longitude']:.2f}</td>")
        cells["ห่างจากตัวแทน"].append(f"<td>{'–' if is_ref else f'{dist:.1f} กม.'}</td>")
        cells["ความลึก"].append(f"<td>{r['depth_km']:.0f} กม.</td>")
        cells["รหัสของแหล่ง"].append(f"<td class='id'>{escape(str(r['source_event_id']))}</td>")
    body = "".join(f"<tr><th scope='row'>{k}</th>{''.join(v)}</tr>" for k, v in cells.items())
    st.markdown(f"<table class='cmp-table'><thead><tr><th></th>{''.join(cols)}</tr></thead>"
                f"<tbody>{body}</tbody></table>", unsafe_allow_html=True)
    if len(reports) >= 2:
        span_t = (reports["event_time_utc"].max() - reports["event_time_utc"].min()).total_seconds()
        span_d = max(haversine_km(a.latitude, a.longitude, b.latitude, b.longitude)
                     for a in reports.itertuples() for b in reports.itertuples())
        span_m = reports["magnitude"].max() - reports["magnitude"].min()
        st.markdown(f"<div class='diffs'><span>เวลาต่างกันสูงสุด <b>{span_t:.0f} วินาที</b></span>"
                    f"<span>ตำแหน่งห่างกันสูงสุด <b>{span_d:.1f} กม.</b></span>"
                    f"<span>ขนาดต่างกัน <b>{span_m:.1f}</b></span></div>", unsafe_allow_html=True)
    else:
        st.markdown("<div class='hint'>มีเพียงแหล่งเดียวที่รายงานเหตุการณ์นี้</div>", unsafe_allow_html=True)

with mini_col, card("ตำแหน่งที่แต่ละแหล่งรายงาน", "ถ้าห่างกันไม่เกิน 100 กม. และเวลาห่างไม่เกิน 60 วินาที ระบบถือเป็นครั้งเดียวกัน"):
    fig = px.scatter_geo(reports, lat="latitude", lon="longitude", color="source", hover_name="source",
                            hover_data={"magnitude": True, "depth_km": True, "latitude": False, "longitude": False,
                                        "source": False},
                            color_discrete_map=SOURCE_COLORS, height=360,
                            labels={"magnitude": "ขนาด", "depth_km": "ลึก (กม.)", "source": "แหล่ง"})
    # วงซ้อนกัน: TMD ใหญ่สุด EMSC เล็กสุด จุดที่ตำแหน่งเกือบเท่ากันจึงยังเห็นครบทุกแหล่ง
    for size, src in ((26, "TMD"), (18, "USGS"), (10, "EMSC")):
        fig.update_traces(marker=dict(size=size, opacity=0.95, line=dict(color=C["white"], width=2)),
                          selector=dict(name=src))
    clat, clon = reports["latitude"].mean(), reports["longitude"].mean()
    style_geo(fig, (clat - 6, clat + 6), (clon - 8, clon + 8))
    add_plates(fig)
    fig.update_layout(legend=dict(orientation="h", x=0, y=-0.02, yanchor="top"))
    chart(fig)

# ---------------------------------------------------------------- seismic waves
section("คลื่นแผ่นดินไหวเดินทางไปถึงไหน",
        f"จำลองคลื่นจากเหตุการณ์ที่เลือกด้านบน ({escape(str(ev['place']))} ขนาด {ev['magnitude']:.1f}) "
        "ด้วยความเร็วเฉลี่ยในเปลือกโลก", kicker="จำลองคลื่น")
wave_col, eta_col = st.columns([8, 4], gap="medium")
with wave_col, card("คลื่น P และคลื่น S", "คลื่น P มาถึงก่อนแต่เบา · คลื่น S มาทีหลังและทำให้สั่นแรง"):
    eta = wave_map(ev["latitude"], ev["longitude"], ev["depth_km"], ev["magnitude"], str(ev["place"]))
with eta_col, card("คลื่นถึงแต่ละเมืองเมื่อไร", "นับจากเวลาที่เกิดแผ่นดินไหว"):
    st.dataframe(
        eta.assign(**{"คลื่น P": eta["p"].map(mmss), "คลื่น S": eta["s"].map(mmss)})
        [["เมือง", "ระยะ (กม.)", "คลื่น P", "คลื่น S"]],
        hide_index=True, use_container_width=True, height=38 + 35 * len(eta),
        column_config={"ระยะ (กม.)": st.column_config.NumberColumn(format="%d")})
    near = eta.iloc[0]
    st.markdown(
        f"<div class='card-note'><b>อ่านอย่างไร</b> ที่{near['เมือง']}จะรู้สึกแรงกระแทกแรกหลังเกิดเหตุ "
        f"{mmss(near['p'])} และสั่นแรงที่สุดหลัง {mmss(near['s'])} ช่วงห่างระหว่างสองคลื่นนี้คือเวลาที่ระบบเตือนภัย"
        "ใช้แจ้งเตือนล่วงหน้าได้ · เป็นค่าประมาณจากความเร็วเฉลี่ย ความเร็วจริงขึ้นกับชั้นหินแต่ละพื้นที่</div>",
        unsafe_allow_html=True)

note("ข้อมูลจากกรมอุตุนิยมวิทยา (web scraping), USGS และ EMSC · เหตุการณ์ที่เวลาห่างกันไม่เกิน 60 วินาที "
     "และอยู่ห่างกันไม่เกิน 100 กม. ถือเป็นแผ่นดินไหวครั้งเดียวกัน · ตัวแทนของแต่ละเหตุการณ์เลือกตามลำดับ TMD → USGS → EMSC")
