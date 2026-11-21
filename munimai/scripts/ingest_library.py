"""Load the OpenStax source clones into library_chunks (retrieval only). Run from munimai/: python scripts/ingest_library.py"""
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
load_dotenv(HERE.parent / ".env")
sys.stdout.reconfigure(encoding="utf-8")
from backend import schema_ext
from backend.analytics import library

c = psycopg.connect(host=os.environ["PGHOST"], port=os.environ["PGPORT"], dbname=os.environ["PGDATABASE"],
                    user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"], connect_timeout=20)
schema_ext.ensure(c)
print(library.ingest(c, HERE.parent / "library_src"))
for q in ["gross margin", "working capital cash conversion cycle", "break-even analysis", "customer lifetime value", "inventory turnover"]:
    hits = library.search(c, q, 2)
    print(f"\n{q!r}: {len(hits)} hit(s)")
    for h in hits:
        print(f"  [{h['book']} / {h['section']}] {library.excerpt(h['text'], q)[:200]}")
