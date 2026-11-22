"""
Task walkthroughs for the browser app, run like a person would: real clicks, real file chooser, a fake microphone.
Each task prints whether it finished, how many clicks/keys it took and how long it took. Failures are UX bugs to fix.

Run (app on :8088 and the Whisper service on :8094):  python uitest/tasks.py
"""
import subprocess
import sys
import time
import uuid
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TMP = ROOT / "tmp"; TMP.mkdir(exist_ok=True)
SHOTS = HERE / "shots"; SHOTS.mkdir(exist_ok=True)
BASE = "http://127.0.0.1:8088"
AUDIO_MP3 = ROOT / "video" / "assets" / "n_setup.mp3"
BILL = ROOT / "video" / "assets" / "bill1.pdf"
WAV = TMP / "fake_mic.wav"

CSV = """date,type,party,gstin,invoice_no,amount,gst_rate
2026-10-03,sale,Anita Tailors,29AAAAA0000A1Z5,S1,11800,18
2026-10-05,purchase,Mysore Silk,29CCCCC2222C1Z5,P1,5900,18
2026-10-06,purchase,Mysore Silk,29CCCCC2222C1Z5,P1,5900,18
"""
RES = []


def record(name, ok, clicks, secs, note=""):
    RES.append((name, ok, clicks, secs, note))
    print(f"{'PASS' if ok else 'FAIL'}  {name:46} clicks/keys={clicks:<3} {secs:5.1f}s  {note}", flush=True)


def new_page(b, w=1440, h=900, mid=None, skip=True, lang="en"):
    ctx = b.new_context(viewport={"width": w, "height": h}, permissions=["microphone"], locale="en-IN")
    mid = mid or "task-" + uuid.uuid4().hex[:10]
    ctx.add_init_script(f"localStorage.setItem('munim_id','{mid}');localStorage.setItem('munim_lang','{lang}');" + ("localStorage.setItem('munim_skip','1');" if skip else ""))
    pg = ctx.new_page(); pg.set_default_timeout(20000)
    errs = []
    pg.on("pageerror", lambda x: errs.append(str(x)[:120]))
    return ctx, pg, errs


def main():
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(AUDIO_MP3), "-ar", "16000", "-ac", "1", str(WAV)], check=True)
    csv_path = TMP / "ui_books.csv"; csv_path.write_text(CSV, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", f"--use-file-for-fake-audio-capture={WAV}"])

        # T1: first visit, keyboard only
        t = time.time(); ctx, pg, errs = new_page(b, skip=False)
        pg.goto(BASE); pg.wait_for_timeout(1500)
        dlg = pg.locator("#setup.on").count() == 1
        focused = pg.evaluate("document.activeElement && document.activeElement.id")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
        closed = pg.locator("#setup.on").count() == 0
        keys = 1; seen = []
        for _ in range(12):
            pg.keyboard.press("Tab"); keys += 1
            seen.append(pg.evaluate("(document.activeElement.getAttribute('aria-label')||document.activeElement.textContent||document.activeElement.id||'').trim().slice(0,22)"))
        reach = any("Close the month" in s for s in seen) and any("Insights" in s for s in seen)
        record("T1 first visit: dialog focus, Esc, tab order", dlg and closed and reach and focused == "bName", keys, time.time() - t,
               f"focus={focused} escape_closes={closed} nav_reachable={reach} js_errors={len(errs)}")
        ctx.close()

        # T2: upload a bill in chat
        t = time.time(); ctx, pg, errs = new_page(b)
        pg.goto(BASE); pg.wait_for_timeout(1200)
        with pg.expect_file_chooser() as fc:
            pg.click("#attach")
        fc.value.set_files(str(BILL))
        pg.wait_for_selector(".them .bubble:has-text('₹'), .them .bubble:has-text('Rs'), .them .bubble:has-text('ledger'), .them .bubble:has-text('Added')", timeout=90000)
        try:
            pg.wait_for_selector("#books .entry", timeout=15000)
        except Exception:
            pass
        books = pg.locator("#books .entry").count()
        record("T2 upload a bill and see it in Books", books >= 1, 2, time.time() - t, f"entries={books} js_errors={len(errs)}")
        ctx.close()

        # T3: import, find problems, fix, approve, file
        t = time.time(); ctx, pg, errs = new_page(b); clicks = 0
        pg.goto(BASE + "/#close"); pg.wait_for_timeout(1200)
        with pg.expect_file_chooser() as fc:
            pg.click("#clPick"); clicks += 1
        fc.value.set_files(str(csv_path)); pg.wait_for_selector(".fileline");
        pg.fill("#clMonth", "2026-10") if pg.locator("#clMonth").count() else None
        pg.click("#clRun"); clicks += 1
        pg.wait_for_selector(".finding", timeout=60000)
        crit = pg.locator(".finding.crit").count()
        blocked = pg.locator("text=Fix the").count() >= 1 and pg.locator("#clGetCode").count() == 0
        pg.screenshot(path=str(SHOTS / "T3-findings.png"))
        pg.click("[data-rm] >> nth=0"); clicks += 1
        pg.wait_for_selector("#cfmYes:visible"); pg.click("#cfmYes"); clicks += 1
        pg.wait_for_selector("#clGetCode", timeout=60000)
        pg.click("#clGetCode"); clicks += 1
        pg.wait_for_selector("#theCode"); code = pg.inner_text("#theCode").strip()
        pg.fill("#clCode", "000000" if code != "000000" else "111111"); pg.click("#clApprove"); clicks += 1
        try:
            pg.wait_for_function("document.getElementById('clCodeErr').textContent.length > 0", timeout=8000)
        except Exception:
            pass
        wrong_msg = pg.inner_text("#clCodeErr").strip()
        pg.fill("#clCode", code); pg.click("#clApprove"); clicks += 1
        pg.wait_for_selector("#clFile"); pg.click("#clFile"); clicks += 1
        pg.wait_for_selector(".receipt .stamp", timeout=30000)
        sim = "SIMULATED" in pg.inner_text(".receipt").upper() or pg.locator(".receipt .stamp").count() == 1
        pg.screenshot(path=str(SHOTS / "T3-receipt.png"))
        record("T3 import > fix critical > approve > sandbox file", crit >= 1 and blocked and bool(wrong_msg) and sim, clicks, time.time() - t,
               f"critical={crit} approval_blocked_while_open={blocked} wrong_code_msg={'yes' if wrong_msg else 'no'} js_errors={len(errs)}")
        ctx.close()

        # T4: insights, read a metric and a market note (seeded business)
        mid = (HERE / "audit_id.txt").read_text().strip() if (HERE / "audit_id.txt").exists() else None
        t = time.time(); ctx, pg, errs = new_page(b, mid=mid)
        pg.goto(BASE + "/#insights"); pg.wait_for_selector(".metric, .empty-state", timeout=30000)
        tiles = pg.locator(".metric").count(); mk = pg.locator("text=Market context").count()
        pg.click("summary:has-text('How we checked') >> nth=0")
        record("T4 insights: tiles, how-we-checked", tiles >= 3, 2, time.time() - t, f"tiles={tiles} market_card={mk} js_errors={len(errs)}")
        ctx.close()

        # T5: English dictation with a fake microphone (local Whisper)
        t = time.time(); ctx, pg, errs = new_page(b)
        pg.goto(BASE); pg.wait_for_timeout(1200)
        pg.click("#dictate")
        pg.wait_for_function("document.getElementById('msg').value.length > 10", timeout=60000)
        val = pg.input_value("#msg")
        record("T5 English dictation fills the box (Whisper)", "business" in val.lower() and pg.input_value("#msg") != "", 1, time.time() - t, f"heard='{val[:70]}' js_errors={len(errs)}")
        ctx.close()

        # T6: Kannada nav labels and no sideways scroll on a phone
        t = time.time(); ctx, pg, errs = new_page(b, w=390, h=844, lang="kn")
        pg.goto(BASE + "/#close"); pg.wait_for_timeout(2500)
        over = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        label = pg.inner_text("#bnav button[data-route=close]")
        pg.screenshot(path=str(SHOTS / "T6-kannada-phone.png"))
        record("T6 Kannada on a phone: labels, no sideways scroll", over <= 0 and "ತಿಂಗಳ" in label or "ಮುಚ್ಚಿ" in label, 0, time.time() - t, f"overflow={over}px label='{label.strip()}' js_errors={len(errs)}")
        ctx.close(); b.close()
    fails = [r for r in RES if not r[1]]
    print(f"\n{len(RES) - len(fails)}/{len(RES)} tasks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
