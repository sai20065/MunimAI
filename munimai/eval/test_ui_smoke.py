"""
Smoke tests for the browser app's endpoints and files. They talk to a RUNNING gateway (default http://127.0.0.1:8088)
and are skipped when it is not up, so the normal suite never depends on a server.

The full click-through lives in uitest/tasks.py (needs Edge, the app and the Whisper service) and uitest/audit.py.

Run (app on :8088, from munimai/):  python -m pytest eval/test_ui_smoke.py -v
"""

from __future__ import annotations

import uuid

import pytest
import requests

BASE = "http://127.0.0.1:8088"


def _up() -> bool:
    try:
        return requests.get(BASE + "/sim/status", timeout=3).ok
    except requests.RequestException:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="gateway not running on :8088")

CSV = ("date,type,party,gstin,invoice_no,amount,gst_rate\n"
       "2026-10-03,sale,Anita,29AAAAA0000A1Z5,S1,11800,18\n"
       "2026-10-05,purchase,Silk,29CCCCC2222C1Z5,P1,5900,18\n"
       "2026-10-06,purchase,Silk,29CCCCC2222C1Z5,P1,5900,18\n")


@pytest.fixture()
def h():
    return {"X-Munim-Id": "pytest-" + uuid.uuid4().hex[:10]}


def test_split_front_end_is_served():
    html = requests.get(BASE + "/").text
    assert '/ui/app.js' in html and '/ui/app.css' in html and '/ui/i18n.js' in html
    for f in ("app.js", "app.css", "i18n.js"):
        r = requests.get(f"{BASE}/ui/{f}")
        assert r.ok and len(r.text) > 1000


def test_all_three_languages_have_the_same_keys():
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "sim_ui" / "i18n.js").read_text(encoding="utf-8")
    blocks = re.split(r"\n \w\w:\{", src)[1:]
    keysets = [set(re.findall(r"(?:^|[,{\s])([A-Za-z0-9]+):(?=['\[])", b, re.M)) for b in blocks]
    assert len(keysets) == 3
    en = keysets[0]
    for other in keysets[1:]:
        assert en - other == set() and other - en == set(), (en - other, other - en)


def test_status_reports_all_services():
    s = requests.get(BASE + "/sim/status").json()
    assert {"boss", "worker", "stt", "math"} <= set(s)


def test_template_csv_downloads_and_parses():
    r = requests.get(BASE + "/sim/template.csv")
    assert r.ok and r.text.startswith("date,type,party")
    from backend.connectors import csvimport
    entries, info = csvimport.parse_books(r.text)
    assert info["rows_ok"] == 2 and not info["rows_rejected"]


def test_series_has_months_and_matching_lengths(h):
    requests.post(BASE + "/sim/import", headers=h, json={"kind": "csv", "text": CSV})
    d = requests.get(BASE + "/sim/series", headers=h).json()
    n = len(d["months"])
    assert n >= 1 and all(len(d[k]) == n for k in ("sales", "purchases", "gross_profit", "margin_pct"))


def test_close_last_restores_the_view_and_entry_actions_work(h):
    requests.post(BASE + "/sim/import", headers=h, json={"kind": "csv", "text": CSV})
    assert requests.get(BASE + "/sim/close/last", headers=h).json()["task"] is None
    c = requests.post(BASE + "/sim/close", headers=h, json={"month": "2026-10", "analyse": False}, timeout=120).json()
    dup = next(f for f in c["findings"] if f["rule"] == "duplicate_invoice")
    assert "P1" in dup["message"] and "p1" not in dup["message"]           # original case is kept
    assert all(str(i) in {str(k) for k in c["entries"]} for i in dup["entry_ids"])
    again = requests.get(BASE + "/sim/close/last", headers=h).json()
    assert again["task"]["id"] == c["task"]["id"] and again["autonomy"] is True
    # a duplicate is fixed by removing one of the two entries, and the critical finding goes away
    assert requests.delete(f"{BASE}/sim/entries/{dup['entry_ids'][0]}", headers=h).json()["ok"] is True
    c2 = requests.post(BASE + "/sim/close", headers=h, json={"month": "2026-10", "analyse": False}, timeout=120).json()
    assert not [f for f in c2["findings"] if f["severity"] == "critical"]


def test_an_entry_of_another_business_cannot_be_removed(h):
    other = {"X-Munim-Id": "pytest-" + uuid.uuid4().hex[:10]}
    requests.post(BASE + "/sim/import", headers=other, json={"kind": "csv", "text": CSV})
    books = requests.get(BASE + "/sim/books", headers=other).json()["entries"]
    assert requests.delete(f"{BASE}/sim/entries/{books[0]['id']}", headers=h).json()["ok"] is False
    assert len(requests.get(BASE + "/sim/books", headers=other).json()["entries"]) == len(books)


def test_stt_never_crashes_on_garbage_audio():
    r = requests.post(BASE + "/sim/stt", files={"file": ("x.webm", b"not audio at all")}, data={"language": "en"}, timeout=60)
    assert r.ok and r.json().get("text", "") == ""


def test_stt_hears_english_speech():
    from pathlib import Path
    mp3 = Path(__file__).resolve().parents[2] / "video" / "assets" / "n_setup.mp3"
    if not mp3.exists():
        pytest.skip("sample audio not present")
    try:
        if not requests.get("http://127.0.0.1:8094/health", timeout=2).ok:
            pytest.skip("Whisper service not running")
    except requests.RequestException:
        pytest.skip("Whisper service not running")
    d = requests.post(BASE + "/sim/stt", files={"file": ("n.mp3", mp3.read_bytes())}, data={"language": "en"}, timeout=120).json()
    assert d["engine"] == "whisper" and "business profile" in d["text"].lower()
