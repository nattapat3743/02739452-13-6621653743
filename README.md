# ระบบรวบรวมข้อมูลแผ่นดินไหวในไทยและประเทศเพื่อนบ้าน

ข้อสอบปลายภาค 02739452 แพลตฟอร์มข้อมูลขนาดใหญ่และการวิเคราะห์ (ภาคต้น 2569)

- **หมวด:** ข้อมูลแผ่นดินไหว
- **ขอบเขต:** แผ่นดินไหวในไทยและประเทศเพื่อนบ้าน (ละติจูด 0–30°N, ลองจิจูด 88–110°E) ย้อนหลัง 30 วัน
- **คำถามที่ตอบ:** ช่วงนี้เกิดแผ่นดินไหวที่ไหนบ้าง และหน่วยงานต่าง ๆ รายงานเหตุการณ์เดียวกันตรงกันแค่ไหน

## แหล่งข้อมูล

| # | แหล่ง | วิธีดึง | ข้อมูล |
|---|---|---|---|
| 1 | กรมอุตุนิยมวิทยา (TMD) — https://earthquake.tmd.go.th/inside.html | **Web scraping** ด้วย `requests` + `BeautifulSoup` (ไม่ใช้ Selenium) | เหตุการณ์ล่าสุดในไทยและใกล้เคียง (~15 รายการต่อครั้ง สะสมขึ้นทุกรอบ) |
| 2 | USGS Earthquake Catalog — https://earthquake.usgs.gov/fdsnws/event/1/ | REST API (GeoJSON) ไม่ต้องใช้ key | ทั่วโลก กรองตามขอบเขต |
| 3 | EMSC Seismic Portal — https://www.seismicportal.eu/fdsnws/event/1/ | REST API (JSON) ไม่ต้องใช้ key | ทั่วโลก กรองตามขอบเขต |

ข้อมูลรวมประมาณ 260+ รายการต่อรอบ (หลังตัดซ้ำเหลือประมาณ 220+ เหตุการณ์)

**robots.txt และ PDPA**
- ก่อน scrape ทุกครั้ง DAG ตรวจ `robots.txt` ด้วย `urllib.robotparser` (เว็บกรมอุตุฯ ไม่มี robots.txt จึงอนุญาต) ตั้ง `User-Agent` ระบุตัวตน และหน่วงเวลาหลังดึง
- ข้อมูลที่เก็บเป็นข้อมูลทางธรณีวิทยาเท่านั้น (เวลา ขนาด พิกัด ความลึก บริเวณ) **ไม่มีข้อมูลส่วนบุคคล**

## สถาปัตยกรรม

```
TMD (scrape) ─┐
USGS (API)  ──┼─> Airflow DAG ─> PostgreSQL (db: quake) ─> Streamlit dashboard
EMSC (API)  ──┘
```

| Service | URL | หมายเหตุ |
|---|---|---|
| Airflow | http://localhost:8080 | user/pass ตาม `.env` (ค่าเริ่มต้น `admin` / `admin`) |
| Dashboard | http://localhost:8501 | หน้า ภาพรวม, วิเคราะห์ และ เบื้องหลังระบบ (เลือกจากแถบเมนูด้านบน) |
| PostgreSQL | localhost:5433 | db `airflow` (metadata), db `quake` (ข้อมูล) |

## DAG `earthquake_pipeline` (รันทุก 30 นาที)

```
create_tables
  -> [TaskGroup: sources]  extract_tmd -> transform_tmd
                           extract_usgs -> transform_usgs     (รันขนานกัน)
                           extract_emsc -> transform_emsc
  -> merge                 (trigger_rule=all_done: แหล่งไหนล่มก็รวมแหล่งที่เหลือต่อ)
  -> check_quality -> branch_on_quality
        ├─ ผ่าน    -> load_raw (UPSERT) -> dedup_publish (ตัดซ้ำข้ามแหล่ง)
        └─ ไม่ผ่าน -> quarantine (เก็บลง earthquakes_rejected ไม่โหลดเข้าตารางหลัก)
  -> log_run               (บันทึกสถานะสำหรับหน้า Pipeline Status)
```

| ระดับ | ทำอย่างไร |
|---|---|
| 1 | extract → transform → load ลง PostgreSQL, เว็บมีตาราง + กราฟ |
| 2 | 3 แหล่งรันขนานใน `TaskGroup("sources")`, แปลงเป็น schema เดียวกัน, `INSERT ... ON CONFLICT (source, source_event_id) DO UPDATE` รันซ้ำแถวไม่เพิ่ม, เว็บมี KPI + ตัวกรอง (วันที่, ขนาด, แหล่ง, จำนวนแหล่งที่ยืนยัน) |
| 3 | `merge` ใช้ `trigger_rule=all_done` → แหล่งล่มแล้วยังไปต่อ; `dedup_publish` จับคู่เหตุการณ์เดียวกันข้ามแหล่ง (เวลาห่าง ≤ 60 วินาที และระยะห่าง ≤ 100 กม. คำนวณด้วย haversine); `check_quality` + `@task.branch` แยกเส้นทางเมื่อข้อมูลเสียเกิน 20% หรือไม่มีข้อมูล |
| โบนัส | หน้า **Pipeline Status** บนเว็บ แสดงสถานะแต่ละรอบ/แต่ละแหล่ง และรายการที่ไม่ผ่านคุณภาพ |

### ตารางในฐานข้อมูล `quake`

| ตาราง | หน้าที่ |
|---|---|
| `earthquakes_raw` | ข้อมูลจากทุกแหล่ง PK `(source, source_event_id)` + `event_key` ที่บอกว่าถูกรวมเป็นเหตุการณ์ไหน |
| `earthquakes` | เหตุการณ์ที่ตัดซ้ำแล้ว (1 แถว = 1 แผ่นดินไหว) พร้อม `sources`, `n_sources`, `mag_min`, `mag_max` |
| `earthquakes_rejected` | รายการที่ไม่ผ่านการตรวจคุณภาพ |
| `pipeline_runs`, `pipeline_source_status` | log สำหรับหน้าสถานะ |

กฎตรวจคุณภาพ: ต้องมี id และเวลา, ขนาดอยู่ในช่วง −2 ถึง 10, ละติจูด/ลองจิจูดถูกต้อง, ความลึก −10 ถึง 800 กม. รายการนอกขอบเขตพื้นที่ถูกกรองทิ้ง (ไม่นับว่าเสีย)

## การวิเคราะห์บนเว็บ (หน้า Analysis)

| หัวข้อ | วิธี | สิ่งที่บอก |
|---|---|---|
| ความลึก 3 มิติ | `plotly scatter_3d` (ลองจิจูด, ละติจูด, −ความลึก) | เห็นแนวแผ่นเปลือกโลกมุดตัวใต้พม่าและทะเลอันดามัน เทียบกับแผ่นดินไหวตื้นในภาคเหนือ |
| กฎ Gutenberg–Richter | หา Mc ด้วย maximum curvature (+0.2), หา b-value ด้วย maximum likelihood (Aki 1965) และ error ตาม Shi & Bolt (1982) | log₁₀N = a − bM โดยทั่วไป b ≈ 1 |
| เทียบขนาดระหว่างแหล่ง | ใช้เหตุการณ์ที่จับคู่ได้จากการตัดซ้ำ แล้วทำ linear regression (`numpy.polyfit`) | แต่ละหน่วยงานรายงานขนาดต่างกันเฉลี่ยกี่แมกนิจูด |

หน้าภาพรวมมีเพิ่มเติม:
- **แผนที่พร้อมเส้นขอบแผ่นเปลือกโลก** (เส้นแดง = เขตมุดตัว) และสวิตช์ **เล่นย้อนหลังทีละวัน** แผนที่วาดในเครื่องด้วย Plotly geo ไม่ต้องโหลด tile จากภายนอก
- **ป้ายระดับความรุนแรง** เล็กมาก (<3) · รู้สึกได้ (3–4) · ปานกลาง (4–5) · แรง (5–6) · รุนแรง (6+) ใช้กรองข้อมูลได้
- **จำลองคลื่นแผ่นดินไหว** คลื่น P (~6 กม./วินาที) และคลื่น S (~3.5 กม./วินาที) แผ่ออกจากเหตุการณ์ที่เลือก พร้อมตารางเวลาที่คลื่นถึง 10 เมืองใหญ่ (ค่าประมาณจากความเร็วเฉลี่ย)
- **คลิกแถวในตารางเหตุการณ์** เพื่อเทียบว่า TMD / USGS / EMSC รายงานเวลา ขนาด และพิกัดของเหตุการณ์นั้นต่างกันเท่าไร (แสดงผลของการตัดซ้ำข้ามแหล่ง)

เส้นขอบแผ่นเปลือกโลก: PB2002 โดย Peter Bird (2003) doi:10.1029/2001GC000252 · GeoJSON โดย Hugo Ahlenius, Nordpil ([fraxen/tectonicplates](https://github.com/fraxen/tectonicplates)) สัญญาอนุญาต ODC-BY 1.0

## วิธีรัน

ต้องมี Docker Desktop (หรือ Docker Engine + Compose v2)

```bash
cp .env.example .env        # ไม่บังคับ ถ้าไม่สร้างจะใช้ค่าเริ่มต้น
docker compose up -d --build
```

รอ 1–2 นาที แล้วเปิด http://localhost:8080 DAG `earthquake_pipeline` จะ unpause และรันเองอัตโนมัติ (หรือกด ▶ Trigger) จากนั้นเปิด http://localhost:8501

ปิดระบบ: `docker compose down` (ลบข้อมูลทั้งหมดด้วย `docker compose down -v`)

> ถ้าเปลี่ยน `POSTGRES_PASSWORD` หลังจากรันไปแล้ว ต้อง `docker compose down -v` ก่อน เพราะรหัสผ่านถูกตั้งตอนสร้าง volume ครั้งแรกเท่านั้น

### ทดสอบ

**UPSERT (รันซ้ำแถวไม่เพิ่ม)** — Trigger DAG 2 ครั้งติดกัน แล้วนับแถว:
```bash
docker compose exec postgres psql -U airflow -d quake -c "SELECT source, count(*) FROM earthquakes_raw GROUP BY 1;"
```

**แหล่งล่ม** — Airflow → Admin → Variables → เพิ่ม `quake_simulate_down` = `EMSC` (หรือ `TMD,USGS`) แล้ว Trigger:
task `extract_emsc` จะเป็นสีแดง แต่ `merge` → `load_raw` → `dedup_publish` ยังสำเร็จ และหน้า Pipeline Status แสดง `PARTIAL` ลบ Variable เพื่อกลับสู่ปกติ

**คุณภาพไม่ผ่าน** — ตั้ง `quake_simulate_down` = `TMD,USGS,EMSC` แล้ว Trigger: ไม่มีข้อมูลเลย → branch ไปที่ `quarantine` และสถานะเป็น `QUALITY_FAILED`

## โครงสร้างโปรเจกต์

```
dags/
  earthquake_pipeline.py   # DAG
  quake_lib.py             # ฟังก์ชัน extract/transform/validate/dedup (ทดสอบแยกจาก Airflow ได้)
web/
  app.py                   # จุดเริ่ม: menu bar ด้านบน + เลือกหน้า (st.navigation)
  views/dashboard.py       # ภาพรวม: ตัวกรอง, KPI, แผนที่ (มี time-lapse), กราฟ, ตาราง
  views/analysis.py        # 3D ความลึก, Gutenberg–Richter, เทียบขนาดระหว่างแหล่ง
  views/status.py          # เบื้องหลังระบบ: ขั้นตอน pipeline, สถานะแต่ละแหล่ง, ประวัติการรัน
  db.py                    # เชื่อม PostgreSQL โดยตรง
  geo.py                   # เส้นขอบแผ่นเปลือกโลก, ระดับความรุนแรง, ระยะทาง
  data/plate_boundaries.geojson  # PB2002 ตัดเฉพาะแถบนี้ (ODC-BY 1.0)
  data/countries_sea.geojson     # เขตแดนประเทศ Natural Earth 1:50m (public domain) ใช้วาดแผนที่คลื่น
  wave.py                  # จำลองคลื่น P/S และเวลาที่คลื่นถึงเมืองใหญ่
  theme.py, DESIGN.md      # component และธีมของเว็บ (อิง DESIGN.md แนว Starbucks จาก getdesign.md)
  Dockerfile, requirements.txt
postgres/init.sql          # สร้าง database quake
docker-compose.yml
Dockerfile.airflow
requirements.txt           # แพ็กเกจเพิ่มเติมของ DAG
.env.example
```
