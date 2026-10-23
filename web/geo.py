"""ข้อมูลเชิงพื้นที่ของเว็บ: เส้นขอบแผ่นเปลือกโลก, ระดับความรุนแรง และระยะทาง"""
import json
import math
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from theme import C

# PB2002 (Peter Bird, 2003) ตัดเฉพาะแถบเอเชียตะวันออกเฉียงใต้ไว้ใน data/ ใช้ภายใต้ ODC-BY 1.0
PLATES_FILE = Path(__file__).parent / "data" / "plate_boundaries.geojson"
PLATES_CREDIT = ("เส้นขอบแผ่นเปลือกโลก: PB2002, Peter Bird (2003) · GeoJSON โดย Hugo Ahlenius, Nordpil "
                 "(ODC-BY 1.0)")

# ระดับความรุนแรงตามขนาด (อธิบายให้คนทั่วไปเข้าใจ)
SEVERITY = [
    (3.0, "เล็กมาก", "s1"),
    (4.0, "รู้สึกได้", "s2"),
    (5.0, "ปานกลาง", "s3"),
    (6.0, "แรง", "s4"),
    (99.0, "รุนแรง", "s5"),
]
SEVERITY_LABELS = [label for _, label, _ in SEVERITY]


def severity(mag: float) -> tuple[str, str]:
    """คืน (ชื่อระดับ, css class) ตามขนาด"""
    for upper, label, css in SEVERITY:
        if mag < upper:
            return label, css
    return SEVERITY[-1][1], SEVERITY[-1][2]


def severity_chip(mag: float) -> str:
    label, css = severity(mag)
    return f"<span class='sev {css}'>{label}</span>"


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


@st.cache_data
def _plate_lines() -> dict[str, tuple[list, list]]:
    """แยกเส้นเป็นเขตมุดตัว (ชื่อมี / หรือ \\ ตาม PB2002) กับรอยต่ออื่น ต่อเส้นด้วย None ให้เป็น trace เดียว"""
    data = json.loads(PLATES_FILE.read_text(encoding="utf-8"))
    out = {"subduction": ([], []), "other": ([], [])}
    for f in data["features"]:
        kind = "subduction" if any(ch in f["properties"]["name"] for ch in "/\\") else "other"
        lons, lats = out[kind]
        for lon, lat in f["geometry"]["coordinates"]:
            lons.append(lon)
            lats.append(lat)
        lons.append(None)
        lats.append(None)
    return out


def style_geo(fig: go.Figure, lat_range: tuple[float, float], lon_range: tuple[float, float]):
    """แผนที่แบบ geo ของ Plotly: วาดชายฝั่ง/เขตแดนในเครื่อง ไม่ต้องโหลด tile จากเซิร์ฟเวอร์ภายนอก
    (tile ของ OpenStreetMap เคยตอบกลับว่างเมื่อถูกจำกัดจำนวนครั้ง ทำให้แผนที่ว่างทั้งแผ่น)"""
    fig.update_geos(
        projection_type="mercator", lataxis_range=list(lat_range), lonaxis_range=list(lon_range),
        resolution=50, showland=True, landcolor=C["canvas"], showocean=True, oceancolor="#DCEBE6",
        showlakes=True, lakecolor="#DCEBE6", showcountries=True, countrycolor="#B9B3A8", countrywidth=0.8,
        showcoastlines=True, coastlinecolor="#9FB3AA", coastlinewidth=0.8, showframe=False,
        bgcolor="rgba(0,0,0,0)")
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))


def add_plates(fig: go.Figure):
    """วาดเส้นขอบแผ่นเปลือกโลกไว้ใต้จุดแผ่นดินไหว"""
    lines = _plate_lines()
    styles = {
        "subduction": ("เขตมุดตัวของแผ่นเปลือกโลก", C["red"], 2.6),
        "other": ("รอยต่อแผ่นเปลือกโลกอื่น ๆ", C["house"], 1.6),
    }
    traces = []
    for kind, (name, color, width) in styles.items():
        lons, lats = lines[kind]
        traces.append(go.Scattergeo(lon=lons, lat=lats, mode="lines", name=name, hoverinfo="name",
                                    line=dict(color=color, width=width), opacity=0.8))
    # ใส่ไว้ก่อน trace ของจุด เพื่อให้เส้นอยู่ใต้วง และ animation frame ยังอ้างถึง trace ของจุดได้ถูกตัว
    fig.add_traces(traces)
    fig.data = fig.data[-2:] + fig.data[:-2]
    if fig.frames:
        for frame in fig.frames:
            frame.traces = [i + 2 for i in (frame.traces or range(len(frame.data)))]
    fig.update_layout(showlegend=True, legend=dict(orientation="h", x=0, y=-0.02, yanchor="top",
                                                   bgcolor="rgba(255,255,255,.85)"))
