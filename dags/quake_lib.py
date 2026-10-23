"""ฟังก์ชันดึง/แปลง/ตัดซ้ำข้อมูลแผ่นดินไหว (ไม่ผูกกับ Airflow จึงทดสอบแยกได้)

Schema กลางของทุกแหล่ง (1 dict ต่อ 1 เหตุการณ์):
    source, source_event_id, event_time_utc (ISO8601), magnitude, latitude,
    longitude, depth_km, place
ไม่มีข้อมูลส่วนบุคคลใด ๆ (PDPA)
"""
from __future__ import annotations

import math
import os
import re
import time
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "KU-02739452-student-project/1.0 (educational; earthquake data)"
TIMEOUT = 30

# ขอบเขต: ไทยและประเทศเพื่อนบ้าน
BBOX = {
    "min_lat": float(os.getenv("QUAKE_MIN_LAT", 0)),
    "max_lat": float(os.getenv("QUAKE_MAX_LAT", 30)),
    "min_lon": float(os.getenv("QUAKE_MIN_LON", 88)),
    "max_lon": float(os.getenv("QUAKE_MAX_LON", 110)),
}
LOOKBACK_DAYS = int(os.getenv("QUAKE_LOOKBACK_DAYS", 30))

TMD_URL = "https://earthquake.tmd.go.th/inside.html"
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
EMSC_URL = "https://www.seismicportal.eu/fdsnws/event/1/query"

# เกณฑ์ตัดซ้ำข้ามแหล่ง: เวลาห่างไม่เกิน 60 วินาที และระยะห่างไม่เกิน 100 กม.
DEDUP_SECONDS = 60
DEDUP_KM = 100
# เมื่อหลายแหล่งรายงานเหตุเดียวกัน ใช้แหล่งตามลำดับนี้เป็นตัวแทน
SOURCE_PRIORITY = ["TMD", "USGS", "EMSC"]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _start_time() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------- robots.txt
def robots_allowed(url: str) -> bool:
    """เคารพ robots.txt; ถ้าเว็บไม่มี robots.txt (404) ถือว่าอนุญาต"""
    parts = urlparse(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    resp = _session().get(robots_url, timeout=TIMEOUT)
    # เว็บกรมอุตุฯ ตอบหน้า 404 แบบ HTML แทน robots.txt -> ไม่มีกฎ
    if resp.status_code >= 400 or "<html" in resp.text[:500].lower():
        return True
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(resp.text.splitlines())
    return rp.can_fetch(USER_AGENT, url)


# ------------------------------------------------------------------ extract
def extract_tmd() -> str:
    """Web scraping หน้า 'แผ่นดินไหวในประเทศและใกล้เคียง' ของกรมอุตุนิยมวิทยา"""
    if not robots_allowed(TMD_URL):
        raise PermissionError(f"robots.txt ไม่อนุญาตให้ดึง {TMD_URL}")
    resp = _session().get(TMD_URL, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    time.sleep(1)  # สุภาพกับเซิร์ฟเวอร์
    return resp.text


def extract_usgs() -> dict:
    params = {
        "format": "geojson",
        "starttime": _start_time(),
        "minlatitude": BBOX["min_lat"],
        "maxlatitude": BBOX["max_lat"],
        "minlongitude": BBOX["min_lon"],
        "maxlongitude": BBOX["max_lon"],
        "orderby": "time",
    }
    resp = _session().get(USGS_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def extract_emsc() -> dict:
    params = {
        "format": "json",
        "starttime": _start_time(),
        "minlat": BBOX["min_lat"],
        "maxlat": BBOX["max_lat"],
        "minlon": BBOX["min_lon"],
        "maxlon": BBOX["max_lon"],
        "limit": 2000,
    }
    resp = _session().get(EMSC_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------- transform
def _float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def transform_tmd(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for tr in soup.find_all("tr", onclick=re.compile(r"/EQ\d+")):
        event_id = re.search(r"/EQ(\d+)", tr["onclick"]).group(1)
        # ช่องในแถว: เวลา | ขนาด | lat | lon | depth | phase | บริเวณ
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 7:
            continue
        utc_match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*UTC", tds[0].get_text(" "))
        if not utc_match:
            continue
        event_time = datetime.strptime(utc_match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        place = " ".join(tds[6].get_text(" ").split())
        records.append({
            "source": "TMD",
            "source_event_id": event_id,
            "event_time_utc": _iso(event_time),
            "magnitude": _float(tds[1].get_text()),
            "latitude": _float(tds[2].get_text()),
            "longitude": _float(tds[3].get_text()),
            "depth_km": _float(tds[4].get_text()),
            "place": place,
        })
    return records


def transform_usgs(data: dict) -> list[dict]:
    records = []
    for f in data.get("features", []):
        p, coords = f["properties"], f["geometry"]["coordinates"]
        records.append({
            "source": "USGS",
            "source_event_id": f["id"],
            "event_time_utc": _iso(datetime.fromtimestamp(p["time"] / 1000, tz=timezone.utc)),
            "magnitude": _float(p.get("mag")),
            "latitude": _float(coords[1]),
            "longitude": _float(coords[0]),
            "depth_km": _float(coords[2]),
            "place": p.get("place"),
        })
    return records


def transform_emsc(data: dict) -> list[dict]:
    records = []
    for f in data.get("features", []):
        p = f["properties"]
        event_time = datetime.fromisoformat(p["time"].replace("Z", "+00:00"))
        records.append({
            "source": "EMSC",
            "source_event_id": p.get("unid") or f.get("id"),
            "event_time_utc": _iso(event_time),
            "magnitude": _float(p.get("mag")),
            "latitude": _float(p.get("lat")),
            "longitude": _float(p.get("lon")),
            # EMSC ให้ depth เป็นค่าบวก (กม.)
            "depth_km": abs(_float(p.get("depth")) or 0) if p.get("depth") is not None else None,
            "place": (p.get("flynn_region") or "").title() or None,
        })
    return records


EXTRACTORS = {"TMD": extract_tmd, "USGS": extract_usgs, "EMSC": extract_emsc}
TRANSFORMERS = {"TMD": transform_tmd, "USGS": transform_usgs, "EMSC": transform_emsc}


# ----------------------------------------------------------- data quality
def validate(record: dict) -> str | None:
    """คืนเหตุผลถ้าไม่ผ่าน, None ถ้าผ่าน"""
    if not record.get("source_event_id"):
        return "missing source_event_id"
    if not record.get("event_time_utc"):
        return "missing event_time_utc"
    mag = record.get("magnitude")
    if mag is None or not (-2 <= mag <= 10):
        return f"invalid magnitude: {mag}"
    lat, lon = record.get("latitude"), record.get("longitude")
    if lat is None or not (-90 <= lat <= 90):
        return f"invalid latitude: {lat}"
    if lon is None or not (-180 <= lon <= 180):
        return f"invalid longitude: {lon}"
    depth = record.get("depth_km")
    if depth is not None and not (-10 <= depth <= 800):
        return f"invalid depth: {depth}"
    return None


def in_scope(record: dict) -> bool:
    return (BBOX["min_lat"] <= record["latitude"] <= BBOX["max_lat"]
            and BBOX["min_lon"] <= record["longitude"] <= BBOX["max_lon"])


# ------------------------------------------------------------------ dedup
def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _ts(record: dict) -> float:
    t = record["event_time_utc"]
    if isinstance(t, datetime):
        return t.timestamp()
    return datetime.fromisoformat(t).timestamp()


def cluster_events(records: list[dict]) -> list[list[dict]]:
    """จับกลุ่มรายการที่เป็นเหตุการณ์เดียวกันข้ามแหล่ง

    สองรายการเป็นเหตุเดียวกันเมื่อมาจากคนละแหล่ง เวลาห่าง <= DEDUP_SECONDS
    และตำแหน่งห่าง <= DEDUP_KM
    """
    clusters: list[list[dict]] = []
    for rec in sorted(records, key=_ts):
        t = _ts(rec)
        best, best_dist = None, None
        for cluster in reversed(clusters):
            head = cluster[0]
            if t - _ts(head) > DEDUP_SECONDS:
                break  # เรียงตามเวลาแล้ว กลุ่มที่เก่ากว่านี้ไม่มีทางตรง
            if any(r["source"] == rec["source"] for r in cluster):
                continue
            dist = haversine_km(head["latitude"], head["longitude"], rec["latitude"], rec["longitude"])
            if dist <= DEDUP_KM and (best_dist is None or dist < best_dist):
                best, best_dist = cluster, dist
        if best is not None:
            best.append(rec)
        else:
            clusters.append([rec])
    return clusters


def representative(cluster: list[dict]) -> dict:
    return min(cluster, key=lambda r: SOURCE_PRIORITY.index(r["source"]))


def event_key(cluster: list[dict]) -> str:
    rep = representative(cluster)
    return f"{rep['source']}:{rep['source_event_id']}"
