"""
Idempotent schema additions for the features added after the first schema:
the eligibility profile (businesses.attrs), sealed bank files (seals) and a
web-click consent source. Safe to run on every start.
"""

from __future__ import annotations

import psycopg


def ensure(conn: psycopg.Connection) -> None:
    conn.execute("ALTER TABLE businesses ADD COLUMN IF NOT EXISTS attrs JSONB NOT NULL DEFAULT '{}'::jsonb")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS seals (
               id             BIGSERIAL PRIMARY KEY,
               token          TEXT        NOT NULL UNIQUE,
               business_id    BIGINT      NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
               kind           TEXT        NOT NULL,
               sealed_at      TIMESTAMPTZ NOT NULL,
               entries        INTEGER     NOT NULL,
               first_date     DATE,
               last_date      DATE,
               total_in_paise BIGINT      NOT NULL,
               total_out_paise BIGINT     NOT NULL,
               ledger_head    TEXT        NOT NULL,
               docs_digest    TEXT        NOT NULL,
               root           TEXT        NOT NULL,
               snapshot       JSONB       NOT NULL,
               pdf_sha256     TEXT
           )""")
    # consent can now be granted by a click in the web app
    conn.execute("ALTER TABLE consents DROP CONSTRAINT IF EXISTS consents_granted_via_check")
    conn.execute("ALTER TABLE consents ADD CONSTRAINT consents_granted_via_check "
                 "CHECK (granted_via IN ('whatsapp_reply','aa_flow','simulated','web_click'))")
    _autonomy(conn)
    conn.commit()


def _autonomy(conn: psycopg.Connection) -> None:
    """Virtual-CA tables: imports, findings, tasks, immutable snapshots, approvals and the filing gate.
    The gate is enforced HERE, in the database, so a bug in an agent cannot file an unapproved return."""
    conn.execute("ALTER TABLE ledger_entries DROP CONSTRAINT IF EXISTS ledger_entries_source_check")
    conn.execute("ALTER TABLE ledger_entries ADD CONSTRAINT ledger_entries_source_check "
                 "CHECK (source IN ('bill_photo','voice','text','upi','manual','tally','csv'))")
    for col in ("invoice_no TEXT", "counterparty_gstin TEXT", "external_ref TEXT"):
        conn.execute(f"ALTER TABLE ledger_entries ADD COLUMN IF NOT EXISTS {col}")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ledger_external_ref_idx "
                 "ON ledger_entries (business_id, external_ref) WHERE external_ref IS NOT NULL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS gstr2b_lines (
               id BIGSERIAL PRIMARY KEY,
               business_id BIGINT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
               supplier_gstin TEXT, supplier_name TEXT, invoice_no TEXT NOT NULL,
               invoice_date DATE, taxable_paise BIGINT NOT NULL, tax_paise BIGINT NOT NULL,
               UNIQUE (business_id, supplier_gstin, invoice_no))""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS autonomy_state (
               business_id BIGINT PRIMARY KEY REFERENCES businesses(id) ON DELETE CASCADE,
               enabled BOOLEAN NOT NULL DEFAULT TRUE,
               updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tasks (
               id BIGSERIAL PRIMARY KEY,
               business_id BIGINT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
               kind TEXT NOT NULL,
               idempotency_key TEXT NOT NULL UNIQUE,
               state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN
                   ('queued','preparing','self_audit','verifier','ready_for_review','approved','filed','blocked','escalated')),
               period_start DATE NOT NULL, period_end DATE NOT NULL,
               max_steps INTEGER NOT NULL DEFAULT 12, steps_used INTEGER NOT NULL DEFAULT 0,
               deadline_at TIMESTAMPTZ NOT NULL,
               note TEXT, snapshot_id BIGINT,
               created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS findings (
               id BIGSERIAL PRIMARY KEY,
               business_id BIGINT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
               task_id BIGINT REFERENCES tasks(id) ON DELETE SET NULL,
               rule TEXT NOT NULL,
               severity TEXT NOT NULL CHECK (severity IN ('info','warn','critical')),
               entry_ids BIGINT[] NOT NULL DEFAULT '{}',
               message TEXT NOT NULL, rule_ref TEXT,
               status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved')),
               created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS snapshots (
               id BIGSERIAL PRIMARY KEY,
               business_id BIGINT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
               task_id BIGINT REFERENCES tasks(id) ON DELETE SET NULL,
               kind TEXT NOT NULL, payload JSONB NOT NULL, sha256 TEXT NOT NULL,
               created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
               UNIQUE (id, sha256))""")
    conn.execute(
        """CREATE OR REPLACE FUNCTION snapshots_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
           BEGIN RAISE EXCEPTION 'snapshots are immutable'; END $$""")
    conn.execute("DROP TRIGGER IF EXISTS snapshots_no_update ON snapshots")
    conn.execute("CREATE TRIGGER snapshots_no_update BEFORE UPDATE ON snapshots "
                 "FOR EACH ROW EXECUTE FUNCTION snapshots_immutable()")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS approval_codes (
               id BIGSERIAL PRIMARY KEY,
               snapshot_id BIGINT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
               code_hash TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL, used_at TIMESTAMPTZ)""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS approvals (
               id BIGSERIAL PRIMARY KEY,
               business_id BIGINT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
               snapshot_id BIGINT NOT NULL, snapshot_hash TEXT NOT NULL,
               approver TEXT NOT NULL, approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
               FOREIGN KEY (snapshot_id, snapshot_hash) REFERENCES snapshots (id, sha256),
               UNIQUE (id, snapshot_hash))""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS filing_attempts (
               id BIGSERIAL PRIMARY KEY,
               business_id BIGINT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
               approval_id BIGINT NOT NULL, snapshot_hash TEXT NOT NULL,
               adapter TEXT NOT NULL, simulated BOOLEAN NOT NULL DEFAULT TRUE,
               status TEXT NOT NULL CHECK (status IN ('filed','failed')),
               receipt JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
               FOREIGN KEY (approval_id, snapshot_hash) REFERENCES approvals (id, snapshot_hash),
               CHECK (adapter <> 'sandbox' OR simulated))""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS formulas (
               id BIGSERIAL PRIMARY KEY,
               business_id BIGINT REFERENCES businesses(id) ON DELETE CASCADE,
               name TEXT NOT NULL, expression TEXT NOT NULL,
               kind TEXT NOT NULL CHECK (kind IN ('predictive','descriptive')),
               target TEXT, unit TEXT, rationale TEXT,
               source TEXT NOT NULL CHECK (source IN ('seed','llm')),
               status TEXT NOT NULL CHECK (status IN ('validated','rejected','indicative','descriptive')),
               evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
               created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
               UNIQUE (business_id, expression))""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS insights (
               id BIGSERIAL PRIMARY KEY,
               business_id BIGINT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
               task_id BIGINT REFERENCES tasks(id) ON DELETE SET NULL,
               title TEXT NOT NULL, body TEXT NOT NULL,
               numbers JSONB NOT NULL DEFAULT '[]'::jsonb,
               grounded BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS market_facts (
               id BIGSERIAL PRIMARY KEY,
               sector TEXT NOT NULL, metric TEXT NOT NULL, value DOUBLE PRECISION NOT NULL, unit TEXT,
               quote TEXT NOT NULL, url TEXT NOT NULL, official BOOLEAN NOT NULL,
               query TEXT, fetched_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS library_chunks (
               id BIGSERIAL PRIMARY KEY,
               book TEXT NOT NULL, section TEXT, text TEXT NOT NULL,
               license TEXT NOT NULL, nc BOOLEAN NOT NULL DEFAULT FALSE,
               source_url TEXT NOT NULL, attribution TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS library_fts_idx ON library_chunks USING GIN (to_tsvector('english', text))")
    conn.execute("ALTER TABLE market_facts ADD COLUMN IF NOT EXISTS value_high DOUBLE PRECISION")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_filing_per_approval ON filing_attempts (approval_id) "
                 "WHERE status = 'filed'")
