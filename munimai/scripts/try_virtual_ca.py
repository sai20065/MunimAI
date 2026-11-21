"""
Walks through the virtual-CA features against the running app (http://127.0.0.1:8088) so you can see each one.
Uses two fresh throw-away browser ids, so it never touches your real business data.

    python scripts/try_virtual_ca.py            # from the munimai folder, with the app running
"""
import sys
import uuid

import requests

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8088"


def call(h, method, path, **kw):
    r = requests.request(method, BASE + path, headers=h, timeout=600, **kw)
    r.raise_for_status()
    return r.json()


def money(p):
    return f"Rs {p / 100:,.2f}"


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
29EEEEE4444E1Z5,Unknown Supplier,X7,2026-10-09,3000,540
"""
CLEAN = """date,type,party,gstin,invoice_no,amount,gst_rate
2026-10-03,sale,Anita Tailors,29AAAAA0000A1Z5,S1,11800,18
2026-10-05,purchase,Mysore Silk,29CCCCC2222C1Z5,P1,5900,18
"""


def show_close(c):
    print(f"\nTask state: {c['task']['state']}  ({c['task']['note']})")
    for f in c["findings"]:
        print(f"  [{f['severity']:8}] {f['rule']:20} {f['message']}")
    if c["snapshot"]:
        r = c["snapshot"]["return"]["figures"]
        print(f"Return draft: output tax {money(r['output_tax_paise'])}, input credit {money(r['input_credit_paise'])}, "
              f"net payable {money(r['net_payable_paise'])}")


print("=== 1. Messy books: import, then let the agent close the month on its own ===")
h1 = {"X-Munim-Id": "try-" + uuid.uuid4().hex[:10]}
print(call(h1, "POST", "/sim/import", json={"kind": "csv", "text": MESSY}))
print(call(h1, "POST", "/sim/import", json={"kind": "gstr2b", "text": GSTR2B}))
c = call(h1, "POST", "/sim/close", json={"month": "2026-10", "analyse": False})
show_close(c)
snap = c["snapshot"]["id"]
code = call(h1, "POST", "/sim/code", json={"snapshot_id": snap})["code"]
print("\nTry to approve while critical findings are open (should be refused):")
print(" ", call(h1, "POST", "/sim/approve", json={"snapshot_id": snap, "code": code}))

print("\n=== 2. Clean books: approve with a code, then file (sandbox only) ===")
h2 = {"X-Munim-Id": "try-" + uuid.uuid4().hex[:10]}
call(h2, "POST", "/sim/import", json={"kind": "csv", "text": CLEAN})
c = call(h2, "POST", "/sim/close", json={"month": "2026-10", "analyse": False})
show_close(c)
snap = c["snapshot"]["id"]
print("Wrong code  :", call(h2, "POST", "/sim/approve", json={"snapshot_id": snap, "code": "000000"}))
code = call(h2, "POST", "/sim/code", json={"snapshot_id": snap})["code"]
appr = call(h2, "POST", "/sim/approve", json={"snapshot_id": snap, "code": code})
print("Right code  :", appr)
print("Filing      :", call(h2, "POST", "/sim/file", json={"approval_id": appr["approval_id"]}))

print("\n=== 3. Books change AFTER approval: filing must be refused ===")
h3 = {"X-Munim-Id": "try-" + uuid.uuid4().hex[:10]}
call(h3, "POST", "/sim/import", json={"kind": "csv", "text": CLEAN})
c3 = call(h3, "POST", "/sim/close", json={"month": "2026-10", "analyse": False})
s3 = c3["snapshot"]["id"]
a3 = call(h3, "POST", "/sim/approve", json={"snapshot_id": s3, "code": call(h3, "POST", "/sim/code", json={"snapshot_id": s3})["code"]})
call(h3, "POST", "/sim/import", json={"kind": "csv", "text": "date,type,party,gstin,invoice_no,amount,gst_rate\n2026-10-20,sale,Late Customer,,S9,2360,18\n"})
print("Filing after a new entry:", call(h3, "POST", "/sim/file", json={"approval_id": a3["approval_id"]}))

print("\n=== 4. Kill switch ===")
print(call(h3, "POST", "/sim/autonomy", json={"enabled": False}))
print("Filing with autonomy off:", call(h3, "POST", "/sim/file", json={"approval_id": a3["approval_id"]}))
call(h3, "POST", "/sim/autonomy", json={"enabled": True})

print("\n=== 5. Math agent insights (needs the second Gemma; takes about a minute) ===")
h4 = {"X-Munim-Id": "try-" + uuid.uuid4().hex[:10]}
rows = ["date,type,party,gstin,invoice_no,amount,gst_rate"]
for m in range(1, 11):
    rows.append(f"2026-{m:02d}-04,purchase,Wholesaler,29CCCCC2222C1Z5,P{m},{60000 + 2500 * m},12")
    rows.append(f"2026-{m:02d}-20,sale,Customers,,S{m},{100000 + 7000 * m},12")
call(h4, "POST", "/sim/import", json={"kind": "csv", "text": "\n".join(rows)})
call(h4, "POST", "/sim/close", json={"month": "2026-10", "analyse": True})
ins = call(h4, "GET", "/sim/insights")
print("Insights:\n" + (ins["insights"][0]["body"] if ins["insights"] else "(none)"))
print("\nFormulas tried:")
for f in ins["formulas"]:
    print(f"  [{f['status']:11}] {f['name'][:48]:48} {f['expression'][:46]}")
