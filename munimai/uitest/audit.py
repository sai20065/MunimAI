"""
Self-run UX audit for the browser app. Drives the real app in Edge at three screen sizes and measures what a person would feel:
console errors, sideways scrolling, tap targets under 44 px, accessibility violations (axe-core, dev-time tool, not shipped),
and keeps a screenshot of every screen for a visual review.

Run (app on :8088):  python uitest/audit.py [seed]
Output: uitest/shots/*.png and uitest/audit.json. Screenshots stay on D:.
"""
import json
import sys
import time
import uuid
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
SHOTS = HERE / "shots"; SHOTS.mkdir(exist_ok=True)
BASE = "http://127.0.0.1:8088"
IDFILE = HERE / "audit_id.txt"
AXE = "https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js"

MESSY = """date,type,party,gstin,invoice_no,amount,gst_rate
2026-10-03,sale,Anita Tailors,29AAAAA0000A1Z5,S1,11800,18
2026-10-04,sale,Ravi Stores,29BBBBB1111B1Z5,S2,23600,18
2026-10-05,purchase,Mysore Silk,29CCCCC2222C1Z5,P1,5900,18
2026-10-06,purchase,Mysore Silk,29CCCCC2222C1Z5,P1,5900,18
2026-10-07,purchase,Ghost Traders,29DDDDD3333D1Z5,G9,11800,18
2026-10-08,purchase,Cash Vendor,,,2360,18
2026-10-09,sale,Walk-in,,S3,5600,12
"""
GSTR2B = """supplier_gstin,supplier_name,invoice_no,invoice_date,taxable,tax
29CCCCC2222C1Z5,Mysore Silk,P1,2026-10-05,5000,900
"""


def seed() -> str:
    """A throw-away business with ten months of books, a messy October and a finished analysis."""
    mid = "audit-" + uuid.uuid4().hex[:10]
    h = {"X-Munim-Id": mid}
    rows = ["date,type,party,gstin,invoice_no,amount,gst_rate"]
    for m in range(1, 10):
        rows.append(f"2026-{m:02d}-04,purchase,Wholesaler,29CCCCC2222C1Z5,P{m},{60000 + 2500 * m},12")
        rows.append(f"2026-{m:02d}-20,sale,Customers,,S{m},{100000 + 7000 * m},12")
    requests.post(BASE + "/sim/import", headers=h, json={"kind": "csv", "text": "\n".join(rows)}, timeout=60)
    requests.post(BASE + "/sim/import", headers=h, json={"kind": "csv", "text": MESSY}, timeout=60)
    requests.post(BASE + "/sim/import", headers=h, json={"kind": "gstr2b", "text": GSTR2B}, timeout=60)
    requests.post(BASE + "/sim/profile", headers={**h, "Content-Type": "application/json"}, json={"name": "Lakshmi Tailoring"}, timeout=30)
    requests.post(BASE + "/sim/close", headers=h, json={"month": "2026-10", "analyse": True}, timeout=900)
    IDFILE.write_text(mid)
    return mid


VIEWPORTS = {"desktop": (1440, 900), "tablet": (820, 1180), "phone": (390, 844)}
ROUTES = ["chat", "close", "insights"]

JS_SMALL = """() => {
  const out = [];
  document.querySelectorAll('button,a[href],input:not([type=hidden]),select,textarea,summary,[role=tab]').forEach(e => {
    const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    if (!r.width || !r.height || cs.visibility === 'hidden' || cs.display === 'none') return;
    if (e.closest('.scrim:not(.on)') || e.closest('[hidden]')) return;
    if (e.matches('input[type=checkbox],input[type=radio]') && e.closest('label') && e.closest('label').getBoundingClientRect().height >= 44) return;
    if (e.tagName === 'A' && getComputedStyle(e).display === 'inline') return;
    if (r.width < 44 || r.height < 44) out.push((e.id || e.className || e.tagName).toString().slice(0, 40) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
  });
  return out.slice(0, 20);
}"""


def audit(theme: str = "light") -> dict:
    mid = IDFILE.read_text() if IDFILE.exists() else seed()
    results = {}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        for vp, (w, h) in VIEWPORTS.items():
            ctx = b.new_context(viewport={"width": w, "height": h}, color_scheme=theme, locale="en-IN")
            ctx.add_init_script(f"localStorage.setItem('munim_id','{mid}');localStorage.setItem('munim_skip','1');localStorage.setItem('munim_lang','en');localStorage.setItem('munim_theme','{theme}');")
            pg = ctx.new_page()
            errs = []
            pg.on("console", lambda m, e=errs: e.append(m.text[:160]) if m.type == "error" else None)
            pg.on("pageerror", lambda x, e=errs: e.append("PAGEERROR " + str(x)[:160]))
            for r in ROUTES:
                pg.goto(f"{BASE}/#{r}"); pg.reload(); pg.wait_for_timeout(2500 if r != "chat" else 1500)
                key = f"{vp}-{theme}-{r}"
                over = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                small = pg.evaluate(JS_SMALL)
                try:
                    pg.add_script_tag(url=AXE)
                    ax = pg.evaluate("axe.run(document,{resultTypes:['violations']}).then(r=>r.violations.map(v=>({id:v.id,impact:v.impact,n:v.nodes.length,help:v.help})))")
                except Exception as e:
                    ax = [{"id": "axe-unavailable", "impact": "n/a", "n": 0, "help": str(e)[:80]}]
                pg.screenshot(path=str(SHOTS / f"{key}.png"), full_page=False)
                results[key] = {"overflow_px": over, "small_targets": small, "axe": [a for a in ax if a["impact"] in ("serious", "critical", "n/a")],
                                "axe_minor": [a["id"] for a in ax if a["impact"] not in ("serious", "critical", "n/a")]}
            results[f"{vp}-{theme}-console"] = sorted(set(errs))
            ctx.close()
        b.close()
    return results


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "seed":
        IDFILE.unlink(missing_ok=True)
    out = {}
    for th in ("light", "dark"):
        out.update(audit(th))
    (HERE / "audit.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    bad = 0
    for k, v in out.items():
        if k.endswith("console"):
            if v:
                bad += len(v); print(f"{k}: CONSOLE ERRORS {v}")
            continue
        issues = []
        if v["overflow_px"] > 0: issues.append(f"sideways scroll {v['overflow_px']}px")
        if v["small_targets"]: issues.append(f"{len(v['small_targets'])} small targets")
        if v["axe"]: issues.append("axe: " + ", ".join(f"{a['id']}({a['n']})" for a in v["axe"]))
        bad += len(issues)
        print(f"{k:30} {'OK' if not issues else '; '.join(issues)}")
    print("issues:", bad)
