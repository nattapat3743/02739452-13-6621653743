"""จำลองคลื่นแผ่นดินไหว (คลื่น P และ S) แผ่ออกจากจุดศูนย์กลาง และเวลาที่คลื่นเดินทางถึงเมืองใหญ่

ใช้ความเร็วเฉลี่ยในเปลือกโลก: คลื่น P ~6.0 กม./วินาที, คลื่น S ~3.5 กม./วินาที
แผนที่วาดเป็น SVG จากไฟล์ในเครื่อง (Natural Earth, public domain) จึงไม่ต้องโหลดอะไรจากภายนอก
"""
import json
import math
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from geo import haversine_km
from theme import C, FONT

P_SPEED, S_SPEED = 6.0, 3.5
DATA = Path(__file__).parent / "data"
VIEW = {"lon": (86.0, 114.0), "lat": (-2.0, 30.0)}
W = 760
CITIES = [
    ("กรุงเทพฯ", 13.75, 100.50), ("เชียงใหม่", 18.79, 98.98), ("เชียงราย", 19.91, 99.83),
    ("ภูเก็ต", 7.88, 98.39), ("ย่างกุ้ง", 16.87, 96.20), ("มัณฑะเลย์", 21.95, 96.08),
    ("เวียงจันทน์", 17.97, 102.63), ("ฮานอย", 21.03, 105.85), ("กัวลาลัมเปอร์", 3.14, 101.69),
    ("บันดาอาเจะห์", 5.55, 95.32),
]


def _projection():
    """equirectangular ที่ปรับด้วย cos(ละติจูดกลาง): ใกล้ศูนย์กลางมุมมองวงกลมยังกลมและสเกลระยะเท่ากันทุกทิศ"""
    lon0, lon1 = VIEW["lon"]
    lat0, lat1 = VIEW["lat"]
    kx = math.cos(math.radians((lat0 + lat1) / 2))
    px_per_deg = W / ((lon1 - lon0) * kx)
    height = (lat1 - lat0) * px_per_deg

    def project(lon, lat):
        return (lon - lon0) * kx * px_per_deg, (lat1 - lat) * px_per_deg

    return project, height, px_per_deg / 111.32  # px ต่อ กม.


@st.cache_data
def _base_svg() -> tuple[str, float, float]:
    project, height, px_per_km = _projection()
    paths = []
    countries = json.loads((DATA / "countries_sea.geojson").read_text(encoding="utf-8"))
    for f in countries["features"]:
        d = []
        for poly in f["geometry"]["coordinates"]:
            for ring in poly:
                pts = [project(x, y) for x, y in ring]
                d.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
        paths.append(f"<path class='land' d='{''.join(d)}'/>")
    plates = json.loads((DATA / "plate_boundaries.geojson").read_text(encoding="utf-8"))
    for f in plates["features"]:
        pts = [project(x, y) for x, y in f["geometry"]["coordinates"]]
        kind = "sub" if any(ch in f["properties"]["name"] for ch in "/\\") else "plate"
        paths.append(f"<path class='{kind}' d='M{'L'.join(f'{x:.1f},{y:.1f}' for x, y in pts)}'/>")
    return "".join(paths), height, px_per_km


def arrivals(lat: float, lon: float, depth_km: float) -> pd.DataFrame:
    """เวลาที่คลื่นถึงแต่ละเมือง ใช้ระยะจากจุดกำเนิดใต้ดิน (รวมความลึก)"""
    rows = []
    for name, clat, clon in CITIES:
        surface = haversine_km(lat, lon, clat, clon)
        dist = math.hypot(surface, 0.0 if pd.isna(depth_km) else depth_km)
        rows.append({"เมือง": name, "lat": clat, "lon": clon, "ระยะ (กม.)": round(surface),
                     "p": dist / P_SPEED, "s": dist / S_SPEED})
    return pd.DataFrame(rows).sort_values("ระยะ (กม.)").reset_index(drop=True)


def mmss(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d} นาที" if m else f"{s} วินาที"


def wave_map(lat: float, lon: float, depth_km: float, magnitude: float, place: str, height_px: int = 560):
    """แผนที่ SVG + animation คลื่น P/S (วนซ้ำ มีปุ่มเล่น/หยุด/เริ่มใหม่)"""
    depth_km = 0.0 if pd.isna(depth_km) else float(depth_km)
    base, h, px_per_km = _base_svg()
    project, _, _ = _projection()
    ex, ey = project(lon, lat)
    table = arrivals(lat, lon, depth_km)
    cities = []
    for r in table.itertuples():
        x, y = project(r.lon, r.lat)
        cities.append({"name": r.เมือง, "x": round(x, 1), "y": round(y, 1), "p": r.p, "s": r.s})
    # ให้ animation ยาวพอที่คลื่น S ไปถึงเมืองที่ไกลที่สุดในมุมมอง แล้วเร่งเวลาให้จบในราว 14 วินาที
    t_max = max(c["s"] for c in cities) * 1.05
    speedup = max(1, round(t_max / 14))

    html = f"""
<style>
  body {{ margin: 0; font-family: {FONT}; color: {C['ink']}; }}
  html, body {{ height: 100%; }}
  /* แผนที่สูงเท่ากรอบเสมอ ส่วนที่เหลือด้านข้างยังเห็นแผ่นดินต่อออกไป (path ยาวเกิน viewBox) */
  .wrap {{ position: relative; height: 100vh; border-radius: 12px; overflow: hidden; background: #DCEBE6; }}
  svg {{ display: block; width: 100%; height: 100%; }}
  .land {{ fill: {C['canvas']}; stroke: #B9B3A8; stroke-width: .7; }}
  .plate {{ fill: none; stroke: {C['house']}; stroke-width: 1.4; opacity: .55; }}
  .sub {{ fill: none; stroke: {C['red']}; stroke-width: 2.2; opacity: .7; }}
  .p-wave {{ fill: rgba(246,176,77,.10); stroke: #E8702A; stroke-width: 2; }}
  .s-wave {{ fill: rgba(194,50,28,.12); stroke: #C2321C; stroke-width: 2.5; }}
  .epi {{ fill: #C2321C; stroke: #fff; stroke-width: 2; }}
  .epi-ring {{ fill: none; stroke: #C2321C; stroke-width: 2; animation: pulse 1.6s ease-out infinite; transform-origin: center; transform-box: fill-box; }}
  @keyframes pulse {{ from {{ transform: scale(1); opacity: .9; }} to {{ transform: scale(3.2); opacity: 0; }} }}
  .city circle {{ fill: #fff; stroke: {C['house']}; stroke-width: 2; transition: fill .3s ease, r .3s ease; }}
  .city text {{ font-size: 12.5px; font-weight: 700; fill: {C['house']}; paint-order: stroke; stroke: #fff; stroke-width: 3px; }}
  .city.p circle {{ fill: #F6B04D; }}
  .city.s circle {{ fill: #C2321C; }}
  .city .t {{ font-size: 11px; font-weight: 800; fill: #C2321C; }}
  .hud {{ position: absolute; left: 12px; top: 12px; background: rgba(255,255,255,.92); border-radius: 12px;
          padding: 10px 14px; box-shadow: 0 1px 3px rgba(0,0,0,.12); font-size: 13px; line-height: 1.5; }}
  .hud b {{ font-size: 22px; color: {C['house']}; }}
  .legend {{ position: absolute; right: 12px; top: 12px; background: rgba(255,255,255,.92); border-radius: 12px;
             padding: 8px 12px; font-size: 12px; line-height: 1.8; box-shadow: 0 1px 3px rgba(0,0,0,.12); }}
  .legend i {{ display: inline-block; width: 18px; height: 0; border-top: 3px solid; vertical-align: middle; margin-right: 6px; }}
  .ctrl {{ position: absolute; left: 12px; bottom: 12px; display: flex; gap: 6px; }}
  button {{ font-family: inherit; font-weight: 700; font-size: 13px; border-radius: 50px; border: 1px solid {C['accent']};
            background: #fff; color: {C['accent']}; padding: 6px 14px; cursor: pointer; transition: all .2s ease; }}
  button:hover {{ background: {C['accent']}; color: #fff; }}
  button:active {{ transform: scale(.95); }}
  @media (prefers-reduced-motion: reduce) {{ .epi-ring {{ animation: none; }} }}
</style>
<div class="wrap">
  <svg viewBox="0 0 {W} {h:.0f}" role="img" aria-label="คลื่นแผ่นดินไหวแผ่ออกจาก {escape(place)}">
    {base}
    <circle id="s" class="s-wave" cx="{ex:.1f}" cy="{ey:.1f}" r="0"/>
    <circle id="p" class="p-wave" cx="{ex:.1f}" cy="{ey:.1f}" r="0"/>
    <g id="cities"></g>
    <circle class="epi-ring" cx="{ex:.1f}" cy="{ey:.1f}" r="7"/>
    <circle class="epi" cx="{ex:.1f}" cy="{ey:.1f}" r="7"/>
  </svg>
  <div class="hud">หลังเกิดเหตุ<br><b id="clock">0 วินาที</b><br>
    <span style="color:{C['muted']}">ขนาด {magnitude:.1f} · ลึก {depth_km:.0f} กม. · เร่งเวลา ×{speedup}</span></div>
  <div class="legend"><i style="border-color:#E8702A"></i>คลื่น P (~{P_SPEED:g} กม./วินาที)<br>
    <i style="border-color:#C2321C"></i>คลื่น S (~{S_SPEED:g} กม./วินาที)<br>
    <i style="border-color:{C['red']};opacity:.7"></i>เขตมุดตัวของแผ่นเปลือกโลก</div>
  <div class="ctrl"><button id="play">หยุด</button><button id="restart">เริ่มใหม่</button></div>
</div>
<script>
const cities = {json.dumps(cities, ensure_ascii=False)};
const pxPerKm = {px_per_km:.5f}, tMax = {t_max:.1f}, speed = {speedup};
const P = document.getElementById('p'), S = document.getElementById('s'), clock = document.getElementById('clock');
const g = document.getElementById('cities'), ns = 'http://www.w3.org/2000/svg';
const fmt = s => s >= 60 ? Math.floor(s / 60) + ':' + String(Math.round(s % 60)).padStart(2, '0') + ' นาที' : Math.round(s) + ' วินาที';
const nodes = cities.map(c => {{
  const el = document.createElementNS(ns, 'g'); el.setAttribute('class', 'city');
  el.innerHTML = `<circle cx="${{c.x}}" cy="${{c.y}}" r="5"/><text x="${{c.x + 8}}" y="${{c.y + 4}}">${{c.name}}</text>` +
                 `<text class="t" x="${{c.x + 8}}" y="${{c.y + 17}}"></text>`;
  g.appendChild(el); return [c, el, el.querySelector('.t')];
}});
let t = 0, last = null, playing = !matchMedia('(prefers-reduced-motion: reduce)').matches;
if (!playing) t = tMax;
function draw() {{
  P.setAttribute('r', (t * {P_SPEED} * pxPerKm).toFixed(1));
  S.setAttribute('r', (t * {S_SPEED} * pxPerKm).toFixed(1));
  clock.textContent = fmt(t);
  nodes.forEach(([c, el, label]) => {{
    el.classList.toggle('p', t >= c.p && t < c.s); el.classList.toggle('s', t >= c.s);
    label.textContent = t >= c.s ? 'สั่นแรงที่ ' + fmt(c.s) : (t >= c.p ? 'รู้สึกที่ ' + fmt(c.p) : '');
  }});
}}
function frame(ts) {{
  if (last !== null && playing) {{ t += (ts - last) / 1000 * speed; if (t > tMax) t = 0; }}
  last = ts; draw(); requestAnimationFrame(frame);
}}
document.getElementById('play').onclick = e => {{ playing = !playing; e.target.textContent = playing ? 'หยุด' : 'เล่น'; }};
document.getElementById('restart').onclick = () => {{ t = 0; playing = true; document.getElementById('play').textContent = 'หยุด'; }};
draw(); requestAnimationFrame(frame);
</script>
"""
    components.html(html, height=height_px)
    return table
