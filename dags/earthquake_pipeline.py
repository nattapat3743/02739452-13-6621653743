"""DAG รวบรวมข้อมูลแผ่นดินไหวในไทยและประเทศเพื่อนบ้านจาก 3 แหล่ง

create_tables
  -> [TaskGroup sources] extract_x -> transform_x  (TMD, USGS, EMSC รันขนานกัน)
  -> merge (all_done: แหล่งไหนล่มก็ยังไปต่อ)
  -> check_quality -> branch_on_quality
        ├─ load_raw (UPSERT) -> dedup_publish (ตัดซ้ำข้ามแหล่ง)
        └─ quarantine (เมื่อคุณภาพไม่ผ่าน)
  -> log_run (บันทึกสถานะสำหรับหน้า Pipeline Status บนเว็บ)

ทดลองให้แหล่งล่ม: ตั้ง Airflow Variable `quake_simulate_down` เป็น เช่น "EMSC" หรือ "TMD,USGS"
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.utils.task_group import TaskGroup
from airflow.utils.trigger_rule import TriggerRule
from psycopg2.extras import execute_values

import quake_lib as ql

CONN_ID = "quake_db"
SOURCES = ["TMD", "USGS", "EMSC"]
MAX_REJECT_RATIO = 0.2  # ถ้าข้อมูลเสียเกิน 20% ไม่โหลดทั้งชุด

DDL = """
CREATE TABLE IF NOT EXISTS earthquakes_raw (
    source           TEXT NOT NULL,
    source_event_id  TEXT NOT NULL,
    event_time_utc   TIMESTAMPTZ NOT NULL,
    magnitude        NUMERIC(4,2),
    latitude         DOUBLE PRECISION,
    longitude        DOUBLE PRECISION,
    depth_km         DOUBLE PRECISION,
    place            TEXT,
    event_key        TEXT,
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_event_id)
);
CREATE TABLE IF NOT EXISTS earthquakes (
    event_key        TEXT PRIMARY KEY,
    event_time_utc   TIMESTAMPTZ NOT NULL,
    magnitude        NUMERIC(4,2),
    latitude         DOUBLE PRECISION,
    longitude        DOUBLE PRECISION,
    depth_km         DOUBLE PRECISION,
    place            TEXT,
    primary_source   TEXT NOT NULL,
    sources          TEXT NOT NULL,
    n_sources        INT NOT NULL,
    mag_min          NUMERIC(4,2),
    mag_max          NUMERIC(4,2),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS earthquakes_rejected (
    source           TEXT NOT NULL,
    source_event_id  TEXT NOT NULL DEFAULT '',
    reason           TEXT NOT NULL,
    payload          JSONB,
    rejected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_event_id)
);
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id           TEXT PRIMARY KEY,
    started_at       TIMESTAMPTZ,
    finished_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    status           TEXT NOT NULL,
    rows_extracted   INT,
    rows_valid       INT,
    rows_rejected    INT,
    events_total     INT,
    note             TEXT
);
CREATE TABLE IF NOT EXISTS pipeline_source_status (
    run_id           TEXT NOT NULL,
    source           TEXT NOT NULL,
    status           TEXT NOT NULL,
    rows             INT,
    checked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, source)
);
"""

COLUMNS = ["source", "source_event_id", "event_time_utc", "magnitude",
           "latitude", "longitude", "depth_km", "place"]


def _simulated_down(source: str) -> bool:
    value = Variable.get("quake_simulate_down", default_var="")
    return source in {s.strip().upper() for s in value.split(",") if s.strip()}


@dag(
    dag_id="earthquake_pipeline",
    description="แผ่นดินไหวไทยและเพื่อนบ้าน: TMD (scrape) + USGS + EMSC",
    schedule="*/30 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(seconds=20)},
    tags=["earthquake", "exam"],
)
def earthquake_pipeline():

    @task
    def create_tables():
        PostgresHook(postgres_conn_id=CONN_ID).run(DDL)

    def make_source_tasks(source: str):
        @task(task_id=f"extract_{source.lower()}")
        def extract():
            if _simulated_down(source):
                raise ConnectionError(f"[simulated] {source} is down")
            return ql.EXTRACTORS[source]()

        @task(task_id=f"transform_{source.lower()}")
        def transform(raw):
            records = ql.TRANSFORMERS[source](raw)
            print(f"{source}: {len(records)} records")
            return records

        return transform(extract())

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def merge(**context):
        ti = context["ti"]
        merged, ok = [], []
        for source in SOURCES:
            records = ti.xcom_pull(task_ids=f"sources.transform_{source.lower()}")
            if records is None:
                print(f"{source}: ไม่มีข้อมูล (แหล่งล่มหรือแปลงไม่สำเร็จ) ข้ามไป")
                continue
            ok.append(source)
            merged.extend(records)
        print(f"แหล่งที่สำเร็จ: {ok}, รวม {len(merged)} รายการ")
        return merged

    @task
    def check_quality(records: list[dict]):
        valid, rejected, out_of_scope = [], [], 0
        for rec in records:
            reason = ql.validate(rec)
            if reason:
                rejected.append({**rec, "reason": reason})
            elif not ql.in_scope(rec):
                out_of_scope += 1
            else:
                valid.append(rec)
        checked = len(valid) + len(rejected)
        ratio = len(rejected) / checked if checked else 1.0
        passed = len(valid) > 0 and ratio <= MAX_REJECT_RATIO
        reason = "" if passed else (
            "ไม่มีข้อมูลจากแหล่งใดเลย" if not checked
            else f"ข้อมูลเสีย {ratio:.0%} เกินเกณฑ์ {MAX_REJECT_RATIO:.0%}")
        print(f"valid={len(valid)} rejected={len(rejected)} out_of_scope={out_of_scope} passed={passed}")
        return {"valid": valid, "rejected": rejected, "passed": passed, "reason": reason}

    @task.branch
    def branch_on_quality(result: dict):
        return "load_raw" if result["passed"] else "quarantine"

    def _save_rejected(cur, rows: list[dict]):
        if not rows:
            return
        execute_values(cur, """
            INSERT INTO earthquakes_rejected (source, source_event_id, reason, payload)
            VALUES %s
            ON CONFLICT (source, source_event_id) DO UPDATE
              SET reason = EXCLUDED.reason, payload = EXCLUDED.payload, rejected_at = now()
        """, [(r["source"], r.get("source_event_id") or "", r["reason"], json.dumps(r, default=str))
              for r in rows])

    @task
    def load_raw(result: dict):
        hook = PostgresHook(postgres_conn_id=CONN_ID)
        with hook.get_conn() as conn, conn.cursor() as cur:
            # UPSERT: รันซ้ำกี่ครั้งจำนวนแถวก็ไม่เพิ่ม
            execute_values(cur, f"""
                INSERT INTO earthquakes_raw ({", ".join(COLUMNS)}) VALUES %s
                ON CONFLICT (source, source_event_id) DO UPDATE SET
                  event_time_utc = EXCLUDED.event_time_utc,
                  magnitude      = EXCLUDED.magnitude,
                  latitude       = EXCLUDED.latitude,
                  longitude      = EXCLUDED.longitude,
                  depth_km       = EXCLUDED.depth_km,
                  place          = EXCLUDED.place,
                  updated_at     = now()
            """, [tuple(r[c] for c in COLUMNS) for r in result["valid"]])
            _save_rejected(cur, result["rejected"])
        return len(result["valid"])

    @task
    def dedup_publish():
        """ตัดรายการซ้ำข้ามแหล่งจากข้อมูลดิบทั้งหมด แล้ว UPSERT ลงตาราง earthquakes"""
        hook = PostgresHook(postgres_conn_id=CONN_ID)
        with hook.get_conn() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {', '.join(COLUMNS)} FROM earthquakes_raw")
            rows = [dict(zip(COLUMNS, r)) for r in cur.fetchall()]
            for r in rows:
                for c in ("magnitude", "latitude", "longitude", "depth_km"):
                    r[c] = float(r[c]) if r[c] is not None else None

            clusters = ql.cluster_events(rows)
            events, key_map = [], []
            for cluster in clusters:
                key, rep = ql.event_key(cluster), ql.representative(cluster)
                mags = [r["magnitude"] for r in cluster]
                srcs = sorted({r["source"] for r in cluster}, key=ql.SOURCE_PRIORITY.index)
                events.append((key, rep["event_time_utc"], rep["magnitude"], rep["latitude"],
                               rep["longitude"], rep["depth_km"], rep["place"], rep["source"],
                               ",".join(srcs), len(srcs), min(mags), max(mags)))
                key_map += [(key, r["source"], r["source_event_id"]) for r in cluster]

            execute_values(cur, """
                INSERT INTO earthquakes (event_key, event_time_utc, magnitude, latitude, longitude,
                    depth_km, place, primary_source, sources, n_sources, mag_min, mag_max)
                VALUES %s
                ON CONFLICT (event_key) DO UPDATE SET
                  event_time_utc = EXCLUDED.event_time_utc, magnitude = EXCLUDED.magnitude,
                  latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude,
                  depth_km = EXCLUDED.depth_km, place = EXCLUDED.place,
                  primary_source = EXCLUDED.primary_source, sources = EXCLUDED.sources,
                  n_sources = EXCLUDED.n_sources, mag_min = EXCLUDED.mag_min,
                  mag_max = EXCLUDED.mag_max, updated_at = now()
            """, events)
            # ลบเหตุการณ์ที่ถูกรวมเข้ากลุ่มอื่นแล้ว (key เดิมไม่มีอยู่จริงอีกต่อไป)
            cur.execute("DELETE FROM earthquakes WHERE NOT (event_key = ANY(%s))",
                        ([e[0] for e in events],))
            execute_values(cur, """
                UPDATE earthquakes_raw r SET event_key = v.event_key
                FROM (VALUES %s) AS v(event_key, source, source_event_id)
                WHERE r.source = v.source AND r.source_event_id = v.source_event_id
            """, key_map)
        print(f"raw={len(rows)} -> unique events={len(events)} (ตัดซ้ำ {len(rows) - len(events)})")
        return len(events)

    @task
    def quarantine(result: dict):
        hook = PostgresHook(postgres_conn_id=CONN_ID)
        batch = result["rejected"] + [
            {**r, "reason": f"batch quarantined: {result['reason']}"} for r in result["valid"]]
        with hook.get_conn() as conn, conn.cursor() as cur:
            _save_rejected(cur, batch)
        print(f"คุณภาพไม่ผ่าน: {result['reason']} -> กักไว้ {len(batch)} รายการ ไม่โหลดเข้าตารางหลัก")

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def log_run(**context):
        dag_run, ti = context["dag_run"], context["ti"]
        states = {t.task_id: t.state for t in dag_run.get_task_instances()}
        hook = PostgresHook(postgres_conn_id=CONN_ID)

        source_rows, extracted = [], 0
        for source in SOURCES:
            tid = f"sources.transform_{source.lower()}"
            records = ti.xcom_pull(task_ids=tid)
            n = len(records) if records is not None else 0
            extracted += n
            status = "success" if states.get(tid) == "success" else "failed"
            source_rows.append((dag_run.run_id, source, status, n))

        result = ti.xcom_pull(task_ids="check_quality") or {}
        if states.get("dedup_publish") == "success":
            status = "SUCCESS" if all(s[2] == "success" for s in source_rows) else "PARTIAL"
        elif states.get("quarantine") == "success":
            status = "QUALITY_FAILED"
        else:
            status = "FAILED"
        events_total = hook.get_first("SELECT count(*) FROM earthquakes")[0]
        failed = [s[1] for s in source_rows if s[2] == "failed"]

        hook.run("""
            INSERT INTO pipeline_runs (run_id, started_at, status, rows_extracted, rows_valid,
                                       rows_rejected, events_total, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO UPDATE SET finished_at = now(), status = EXCLUDED.status,
              rows_extracted = EXCLUDED.rows_extracted, rows_valid = EXCLUDED.rows_valid,
              rows_rejected = EXCLUDED.rows_rejected, events_total = EXCLUDED.events_total,
              note = EXCLUDED.note
        """, parameters=(dag_run.run_id, dag_run.start_date, status, extracted,
                         len(result.get("valid", [])), len(result.get("rejected", [])),
                         events_total,
                         "; ".join(filter(None, [result.get("reason"),
                                                 f"แหล่งล่ม: {', '.join(failed)}" if failed else ""]))))
        with hook.get_conn() as conn, conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO pipeline_source_status (run_id, source, status, rows) VALUES %s
                ON CONFLICT (run_id, source) DO UPDATE
                  SET status = EXCLUDED.status, rows = EXCLUDED.rows, checked_at = now()
            """, source_rows)
        print(f"run status = {status}")

    tables = create_tables()
    with TaskGroup("sources") as sources:
        for source in SOURCES:
            make_source_tasks(source)

    merged = merge()
    quality = check_quality(merged)
    branch = branch_on_quality(quality)
    loaded = load_raw(quality)
    published = dedup_publish()
    quarantined = quarantine(quality)
    logged = log_run()

    tables >> sources >> merged
    branch >> [loaded, quarantined]
    loaded >> published
    [published, quarantined] >> logged


earthquake_pipeline()
