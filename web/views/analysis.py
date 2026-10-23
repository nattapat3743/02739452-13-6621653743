"""หน้าวิเคราะห์: มุมมอง 3 มิติตามความลึก, กฎ Gutenberg–Richter, เทียบขนาดระหว่างแหล่ง"""
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from db import query, tables_ready
from theme import C, SEQ_SCALE, SOURCE_COLORS, card, card_note, chart, kpis, page_header, section

if not tables_ready():
    page_header("Analysis", "วิเคราะห์เชิงลึก")
    st.warning("ยังไม่มีข้อมูล: รอ DAG รันครั้งแรกก่อน")
    st.stop()

events = query("SELECT * FROM earthquakes")
for c in ("magnitude", "depth_km", "latitude", "longitude"):
    events[c] = events[c].astype(float)

page_header("Analysis · Seismology",
            "แผ่นดินไหวแถบนี้มีลักษณะอย่างไร",
            f"วิเคราะห์จาก <b>{len(events):,} เหตุการณ์</b>ที่ตัดซ้ำแล้ว เพื่อตอบสามคำถาม: เกิดลึกแค่ไหน "
            "ขนาดกระจายตัวตามกฎธรรมชาติหรือไม่ และแต่ละหน่วยงานวัดขนาดได้ตรงกันเพียงใด")

# ใช้ segmented control แทน st.tabs: st.tabs วาดแท็บที่ซ่อนไว้ล่วงหน้าด้วยความกว้างที่ผิด กราฟจึงล้นการ์ด
VIEWS = ["ความลึก", "Gutenberg–Richter", "เทียบระหว่างแหล่ง"]
HEADS = {
    VIEWS[0]: ("เกิดลึกแค่ไหน", "ตำแหน่งและความลึกของทุกเหตุการณ์ในสามมิติ"),
    VIEWS[1]: ("ขนาดกระจายตัวตามกฎธรรมชาติไหม", "จำนวนเหตุการณ์ลดลงตามขนาดแบบ log-linear หรือไม่"),
    VIEWS[2]: ("แต่ละหน่วยงานวัดตรงกันไหม", "เทียบขนาดของเหตุการณ์เดียวกันที่หลายแหล่งรายงาน"),
}
view = st.session_state.get("view") or VIEWS[0]
view_col = section(*HEADS[view], kicker=f"มุมมอง {VIEWS.index(view) + 1} จาก 3", controls=True)
with view_col.container(key="viewbar"):
    view = st.segmented_control("มุมมอง", VIEWS, default=VIEWS[0], key="view",
                                label_visibility="collapsed") or VIEWS[0]

# ------------------------------------------------------------ 3D depth
if view == VIEWS[0]:
    df = events.dropna(subset=["depth_km"])
    kpis([
        {"label": "ความลึกเฉลี่ย", "value": f"{df['depth_km'].mean():.0f}", "unit": "กม.", "accent": True},
        {"label": "ลึกที่สุด", "value": f"{df['depth_km'].max():.0f}", "unit": "กม.",
         "sub": df.loc[df["depth_km"].idxmax(), "place"]},
        {"label": "ลึกกว่า 70 กม.", "value": f"{(df['depth_km'] >= 70).mean():.0%}",
         "sub": "ระดับกลาง (intermediate-depth)"},
    ])
    st.write("")
    with card("ตำแหน่งตามความลึก (3 มิติ)", "ลากเพื่อหมุน เลื่อนล้อเมาส์เพื่อซูม"):
        fig = px.scatter_3d(
            df, x="longitude", y="latitude", z=-df["depth_km"], color="depth_km",
            size=df["magnitude"].clip(lower=1) ** 2, size_max=14, opacity=0.9,
            color_continuous_scale=SEQ_SCALE, hover_name="place",
            hover_data={"magnitude": True, "depth_km": True, "sources": True},
            labels={"longitude": "ลองจิจูด", "latitude": "ละติจูด", "z": "ความลึก (กม.)",
                    "depth_km": "ลึก (กม.)", "magnitude": "ขนาด", "sources": "แหล่ง"},
            height=600)
        axis = dict(backgroundcolor=C["surface"], gridcolor=C["line"], color=C["muted"])
        fig.update_layout(
            scene=dict(xaxis=axis, yaxis=axis, zaxis={**axis, "title": "ความลึก (กม.)"},
                       aspectmode="manual", aspectratio=dict(x=1.4, y=1.6, z=0.7),
                       camera=dict(eye=dict(x=1.6, y=-1.4, z=0.7))),
            coloraxis_colorbar=dict(title="ลึก (กม.)", thickness=10, len=0.6))
        chart(fig)
        card_note("<b>ข้อสังเกต</b> เมื่อหมุนดูจากด้านข้าง เหตุการณ์ใต้พม่าและทะเลอันดามันเรียงเป็นแนวเอียงลึกลงไปทางตะวันออก "
                  "ซึ่งคือแผ่นอินเดียที่มุดตัวลงใต้แผ่นซุนดา ส่วนแผ่นดินไหวในภาคเหนือของไทยและลาวส่วนใหญ่ตื้นกว่า 30 กม. "
                  "เพราะเกิดจากรอยเลื่อนในเปลือกโลก")

# ------------------------------------------------------ Gutenberg–Richter
if view == VIEWS[1]:
    mags = events["magnitude"].dropna().round(1)
    dm = 0.1
    bins = np.round(np.arange(mags.min(), mags.max() + dm, dm), 1)
    counts = mags.value_counts().reindex(bins, fill_value=0)
    cum = counts[::-1].cumsum()[::-1]  # N(≥M)

    # Mc ด้วยวิธี maximum curvature (+0.2 ตามที่นิยมแก้ค่าที่ต่ำเกินจริง)
    mc = float(counts.idxmax()) + 0.2
    above = mags[mags >= mc - 1e-9]
    if len(above) < 10:
        st.info("ข้อมูลเหนือ Mc ยังน้อยเกินไป (ต้องมีอย่างน้อย 10 เหตุการณ์)")
    else:
        # b-value แบบ maximum likelihood (Aki 1965) พร้อม error ของ Shi & Bolt (1982)
        b = np.log10(np.e) / (above.mean() - (mc - dm / 2))
        b_err = 2.3 * b ** 2 * np.sqrt(((above - above.mean()) ** 2).sum() / (len(above) * (len(above) - 1)))
        a = np.log10(len(above)) + b * mc

        kpis([
            {"label": "b-value", "value": f"{b:.2f}", "unit": f"± {b_err:.2f}", "accent": True,
             "sub": "ค่าปกติของเปลือกโลก ≈ 1.0"},
            {"label": "a-value", "value": f"{a:.2f}", "sub": "ระดับกิจกรรมโดยรวม"},
            {"label": "Mc", "value": f"{mc:.1f}", "sub": "ขนาดต่ำสุดที่ตรวจจับได้ครบ"},
            {"label": "ใช้คำนวณ", "value": f"{len(above):,}", "unit": "เหตุการณ์"},
        ])
        st.write("")
        with card("การกระจายตัวของขนาด", "แกนตั้งเป็นสเกล log เส้นตรงคือกฎ Gutenberg–Richter ที่ fit ได้"):
            fig = go.Figure()
            fig.add_bar(x=counts.index, y=counts.values, name="จำนวนต่อช่วงขนาด",
                        marker_color=C["taupe"])
            fig.add_scatter(x=cum.index, y=cum.values, mode="markers", name="สะสม N(≥M)",
                            marker=dict(color=C["accent"], size=7))
            m_line = np.linspace(mc, mags.max(), 50)
            fig.add_scatter(x=m_line, y=10 ** (a - b * m_line), mode="lines",
                            name=f"log₁₀N = {a:.2f} − {b:.2f}M", line=dict(color=C["ink"], width=2.5))
            fig.add_vline(x=mc, line_dash="dot", line_color=C["muted"],
                          annotation_text=f"Mc {mc:.1f}", annotation_font_color=C["muted"])
            fig.update_layout(yaxis_type="log", xaxis_title="ขนาด (M)", yaxis_title="จำนวนเหตุการณ์",
                              height=440, legend=dict(orientation="h", y=1.1, x=0), bargap=0.15)
            chart(fig)
            verdict = ("ใกล้ 1.0 ตามค่าปกติของเปลือกโลก" if 0.8 <= b <= 1.2 else
                       "สูงกว่าปกติ: มีเหตุการณ์ขนาดเล็กในสัดส่วนสูง ซึ่งมักพบในกลุ่ม swarm" if b > 1.2 else
                       "ต่ำกว่าปกติ: ส่วนหนึ่งน่าจะเกิดจากข้อมูลขนาดเล็กยังเก็บได้ไม่ครบ (Mc ต่ำไป) "
                       "จึงยังสรุปทางธรณีวิทยาไม่ได้")
            card_note(f"<b>อ่านค่าอย่างไร</b> ทุกครั้งที่ขนาดเพิ่ม 1 จำนวนเหตุการณ์จะลดลงประมาณ 10<sup>b</sup> เท่า "
                      f"ค่า b ที่ได้คือ <b>{b:.2f}</b> {verdict} "
                      "ข้อจำกัด: ข้อมูลรวมขนาดหลายประเภท (ML, mb, Mw) จากหลายหน่วยงาน และมีช่วงเวลาเพียง 30 วัน")

# ---------------------------------------------------- source comparison
if view == VIEWS[2]:
    raw = query("""SELECT r.event_key, r.source, r.magnitude
                   FROM earthquakes_raw r JOIN earthquakes e USING (event_key)
                   WHERE e.n_sources >= 2""")
    raw["magnitude"] = raw["magnitude"].astype(float)
    wide = raw.pivot_table(index="event_key", columns="source", values="magnitude", aggfunc="first")

    pairs = [(x, y) for x, y in [("USGS", "EMSC"), ("USGS", "TMD"), ("EMSC", "TMD")]
             if x in wide and y in wide and len(wide[[x, y]].dropna()) >= 2]
    if not pairs:
        st.info("ยังไม่มีเหตุการณ์ที่หลายแหล่งรายงานตรงกันมากพอ")
        st.stop()

    summary = []
    for x, y in pairs:
        d = wide[[x, y]].dropna()
        diff = d[y] - d[x]
        summary.append({"คู่ที่เทียบ": f"{y} เทียบกับ {x}", "จำนวนคู่": len(d),
                        "ต่างเฉลี่ย": diff.mean(), "ต่างสัมบูรณ์เฉลี่ย": diff.abs().mean(),
                        "สหสัมพันธ์ (r)": d[x].corr(d[y]) if len(d) >= 3 else None})

    options = [f"{x} vs {y}" for x, y in pairs]
    choice = st.segmented_control("คู่ที่เทียบ", options, default=options[0]) or options[0]
    x, y = choice.split(" vs ")
    d = wide[[x, y]].dropna().reset_index()
    bias = (d[y] - d[x]).mean()

    kpis([
        {"label": f"{y} ต่างจาก {x} เฉลี่ย", "value": f"{bias:+.2f}", "unit": "M", "accent": True,
         "sub": f"จาก {len(d)} เหตุการณ์ที่จับคู่ได้"},
        {"label": "ต่างสัมบูรณ์เฉลี่ย", "value": f"{(d[y] - d[x]).abs().mean():.2f}", "unit": "M"},
        {"label": "สหสัมพันธ์ (r)", "value": f"{d[x].corr(d[y]):.2f}" if len(d) >= 3 else "-",
         "sub": "1.0 = ขึ้นลงไปด้วยกันพอดี"},
    ])
    st.write("")
    left, right = st.columns([3, 2], gap="medium")
    with left, card(f"ขนาดจาก {x} เทียบกับ {y}", "จุดบนเส้นประแปลว่าสองแหล่งรายงานตรงกันพอดี"):
        fig = px.scatter(d, x=x, y=y, hover_name="event_key", height=400,
                         labels={x: f"ขนาดจาก {x}", y: f"ขนาดจาก {y}"})
        fig.update_traces(marker=dict(color=SOURCE_COLORS[y], size=11, opacity=0.85,
                                      line=dict(color=C["white"], width=1.5)), name="เหตุการณ์")
        lo, hi = float(d[[x, y]].min().min()) - 0.2, float(d[[x, y]].max().max()) + 0.2
        fig.add_scatter(x=[lo, hi], y=[lo, hi], mode="lines", name="ตรงกันพอดี (y = x)",
                        line=dict(color=C["muted"], dash="dot"))
        if len(d) >= 3:
            slope, intercept = np.polyfit(d[x], d[y], 1)
            fig.add_scatter(x=[lo, hi], y=[slope * lo + intercept, slope * hi + intercept], mode="lines",
                            name=f"regression: {y} = {slope:.2f}·{x} {intercept:+.2f}",
                            line=dict(color=C["accent"], width=2.5))
        fig.update_layout(legend=dict(orientation="h", y=1.12, x=0))
        chart(fig)

    with right, card("สรุปทุกคู่", "เทียบทุกคู่แหล่งที่มีเหตุการณ์ตรงกัน"):
        st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True,
                     column_config={
                         "ต่างเฉลี่ย": st.column_config.NumberColumn(format="%+.2f"),
                         "ต่างสัมบูรณ์เฉลี่ย": st.column_config.NumberColumn(format="%.2f"),
                         "สหสัมพันธ์ (r)": st.column_config.NumberColumn(format="%.2f")})
        card_note(f"<b>ทำไมไม่ตรงกัน</b> แต่ละหน่วยงานใช้สถานีวัดและสูตรคำนวณต่างกัน "
                  f"เช่น TMD มักใช้ ML (local magnitude) ส่วน USGS ใช้ mb หรือ Mww "
                  f"โดยเฉลี่ย {y} รายงาน{'สูง' if bias > 0 else 'ต่ำ'}กว่า {x} อยู่ {abs(bias):.2f} แมกนิจูด")
