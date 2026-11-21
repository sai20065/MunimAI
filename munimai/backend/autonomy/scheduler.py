"""
The scheduler: wakes up on a timer, makes sure each business has its month-close task for the
last full month, and runs anything queued. Tasks live in the database, so if the process dies
the next tick resumes them.

Off by default. Set AUTONOMY_TICK_S (seconds) to start the background thread in the gateway.
"""

from __future__ import annotations

import threading
import time
from datetime import date
from typing import Callable, Optional

import psycopg

from ..agents import coordinator
from ..filing import gate
from ..trace import Trace


def tick(conn: psycopg.Connection, today: Optional[date] = None) -> list[dict]:
    today = today or date.today()
    start, end = coordinator.previous_month(today)
    out = []
    biz = conn.execute(
        "SELECT DISTINCT business_id FROM ledger_entries WHERE entry_date BETWEEN %s AND %s", (start, end)).fetchall()
    for (bid,) in biz:
        if not gate.autonomy_enabled(conn, bid):
            continue
        tid = coordinator.ensure_task(conn, bid, start, end)
        status = coordinator.task_status(conn, tid)
        if status["state"] == "queued":
            out.append(coordinator.run_task(conn, tid, Trace(business_id=bid)))
    return out


def start_background(get_conn: Callable[[], psycopg.Connection], interval_s: int) -> threading.Thread:
    def loop() -> None:
        while True:
            try:
                c = get_conn()
                try:
                    tick(c)
                finally:
                    c.close()
            except Exception:
                pass                       # a failed tick must never kill the loop; next tick retries
            time.sleep(interval_s)
    th = threading.Thread(target=loop, name="autonomy-scheduler", daemon=True)
    th.start()
    return th
