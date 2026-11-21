"""
Tests for the Math agent. The model only proposes; these tests check that code decides:
the formula language is locked down, backtests separate real signal from noise, short histories are labelled
indicative, invented numbers are blocked, and web facts must be quoted from the page.

Offline except the two end-to-end tests at the bottom (they need the database).
Run (from munimai/):  python -m pytest eval/test_math_agent.py -v
"""

from __future__ import annotations

import os
import uuid
from datetime import date

import numpy as np
import pytest

from backend.analytics import backtest, market, series as S
from backend.analytics.grounding import ungrounded_numbers
from backend.analytics.safe_expr import FormulaError, compile_formula

U = S.UNITS


def _series(n, sales, purchases):
    base = {k: np.zeros(n) for k in U}
    base["sales"], base["purchases"] = np.asarray(sales, float), np.asarray(purchases, float)
    base["gross_profit"] = base["sales"] - base["purchases"]
    return base


# ------------------------------------------------------------------ the formula language
@pytest.mark.parametrize("bad", [
    "__import__('os').system('echo hi')", "sales.real", "open('x')", "[sales]", "lambda: 1", "sales if 1 else 2",
    "sales**9", "sales + sales_count", "growth(sales) + sales", "exec('1')", "'text'", "sales[0]", "foo(sales)",
    "roll(sales, k=3)", "a" * 300,
])
def test_unsafe_or_wrong_formulas_are_rejected(bad):
    with pytest.raises(FormulaError):
        compile_formula(bad, U)


def test_good_formula_computes_and_has_units():
    f = compile_formula("(sales - purchases) / sales", U)
    assert f.unit == ()
    out = f.evaluate({"sales": np.array([100.0, 200.0]), "purchases": np.array([60.0, 150.0])})
    assert np.allclose(out, [0.4, 0.25])


def test_division_by_zero_is_nan_not_an_error_or_zero():
    f = compile_formula("purchases / sales", U)
    out = f.evaluate({"sales": np.array([0.0, 10.0]), "purchases": np.array([5.0, 5.0])})
    assert np.isnan(out[0]) and out[1] == 0.5


def test_rolling_and_growth():
    f = compile_formula("roll(sales, 3)", U)
    out = f.evaluate({"sales": np.array([1.0, 2, 3, 4])})
    assert np.isnan(out[1]) and out[2] == 2 and out[3] == 3
    g = compile_formula("growth(sales)", U).evaluate({"sales": np.array([100.0, 110.0])})
    assert abs(g[1] - 0.1) < 1e-9


# ------------------------------------------------------------------ backtests
def test_real_signal_is_validated():
    rng = np.random.default_rng(3)
    n = 14
    purchases = 100 + 40 * rng.random(n)
    sales = np.zeros(n); sales[0] = 150
    sales[1:] = 2.0 * purchases[:-1] + rng.normal(0, 1.5, n - 1)         # last month's purchases drive this month's sales
    f = compile_formula("purchases", U)
    ev = backtest.evaluate_predictive(f, _series(n, sales, purchases), "sales", n, n_candidates=3)
    assert ev.status == "validated", ev


def test_pure_noise_is_rejected_almost_always():
    f = compile_formula("purchases", U)
    n, wins = 14, 0
    for seed in range(40):
        rng = np.random.default_rng(seed)
        ev = backtest.evaluate_predictive(f, _series(n, 100 + 30 * rng.random(n), 100 + 30 * rng.random(n)), "sales", n, n_candidates=8)
        wins += ev.status == "validated"
    assert wins <= 3, f"{wins}/40 noise series passed; the test is too easy to pass by luck"


def test_short_history_is_labelled_indicative_never_validated():
    f = compile_formula("purchases", U)
    ev = backtest.evaluate_predictive(f, _series(4, [1, 2, 3, 4], [1, 2, 3, 4]), "sales", 4)
    assert ev.status == "indicative" and "months" in ev.reason
    d = backtest.evaluate_descriptive(compile_formula("gross_profit / sales", U), _series(4, [10, 11, 10, 12], [6, 6, 7, 6]), 4)
    assert d.status == "indicative"


def test_formula_with_mostly_undefined_values_is_rejected():
    f = compile_formula("purchases / sales", U)
    ev = backtest.evaluate_descriptive(f, _series(8, np.zeros(8), np.ones(8)), 8)
    assert ev.status == "rejected"


# ------------------------------------------------------------------ number grounding
def test_invented_numbers_are_caught_and_computed_ones_pass():
    allowed = [0.351, 35.1, 312000.0, 6.0]
    assert ungrounded_numbers("Your gross margin is 35.1% over 6 months.", allowed) == []
    assert ungrounded_numbers("Purchases were Rs 3,12,000.", allowed) == []             # Indian digit grouping
    assert ungrounded_numbers("Your gross margin is 42% this month.", allowed) == ["42%"]
    assert ungrounded_numbers("Expect sales of Rs 5,00,000 next year.", allowed)       # invented


def test_years_and_small_month_counts_are_not_flagged():
    assert ungrounded_numbers("Since 2026, over the last 3 months.", [1.0]) == []


def test_a_ratio_may_not_be_reported_as_rupees_but_may_be_a_percentage():
    allowed = [0.499]
    assert ungrounded_numbers("Credit equals 49.9 rupees for every rupee of tax.", allowed) == ["49.9"]
    assert ungrounded_numbers("Credit is 49.9% of the tax charged.", allowed) == []


def test_trivial_and_mislabelled_formulas_are_rejected():
    from backend.agents.math_agent import MathAgent
    n = 8
    rng = np.random.default_rng(1)
    s = {k: 100 + 20 * rng.random(n) for k in U}
    s["avg_sale"] = s["sales"].copy()                       # abs(sales - avg_sale) is 0 every month
    ma = MathAgent(None)
    const, _ = ma.evaluate(dict(name="Deviation", expression="abs(sales - avg_sale)", kind="descriptive", target=None, source="llm"), U, s, n, 3)
    assert const["status"] == "rejected" and "constant" in const["evidence"]["reason"]
    mislabelled, _ = ma.evaluate(dict(name="Tax Efficiency Ratio", expression="output_tax - input_tax", kind="descriptive", target=None, source="llm"), U, s, n, 3)
    assert mislabelled["status"] == "rejected" and "ratio" in mislabelled["evidence"]["reason"]


# ------------------------------------------------------------------ web facts must be quoted from the page
class FakeLLM:
    def __init__(self, payload=None, text="- ok"):
        self.payload, self.text = payload, text

    def json_call(self, *a, **k):
        return self.payload

    def chat(self, *a, **k):
        class R:  # minimal result
            pass
        r = R(); r.text = self.text
        return r

    def health(self):
        return True


def _hit(text):
    return market.websearch.WebHit(url="https://example.com/a", title="t", snippet=text, official=False, page_text=text)


def test_market_fact_must_be_quoted_from_the_page():
    page = "Retail kirana stores in India typically earn a gross margin of 18% on groceries."
    good = FakeLLM({"facts": [{"metric": "gross margin", "value": 18, "unit": "%",
                               "quote": "typically earn a gross margin of 18% on groceries"}]})
    assert len(market.extract(good, "trading", _hit(page))) == 1
    invented_quote = FakeLLM({"facts": [{"metric": "gross margin", "value": 18, "unit": "%", "quote": "margins are 18% everywhere"}]})
    assert market.extract(invented_quote, "trading", _hit(page)) == []
    wrong_number = FakeLLM({"facts": [{"metric": "gross margin", "value": 25, "unit": "%",
                                       "quote": "typically earn a gross margin of 18% on groceries"}]})
    assert market.extract(wrong_number, "trading", _hit(page)) == []


# ------------------------------------------------------------------ series from rows
def test_series_from_rows_ignores_unreviewed_and_trims_empty_months():
    rows = [dict(entry_date=date(2026, 9, 5), direction="in", amount_paise=11800_00, gst_rate_bp=1800, needs_review=False),
            dict(entry_date=date(2026, 10, 5), direction="out", amount_paise=5900_00, gst_rate_bp=1800, needs_review=False),
            dict(entry_date=date(2026, 10, 6), direction="in", amount_paise=999_00, gst_rate_bp=1800, needs_review=True)]
    months, s = S.trim_leading_empty(*S.series_from_rows(rows, (2026, 10), 6))
    assert months == [(2026, 9), (2026, 10)]
    assert s["sales"][0] == 10000 and s["purchases"][1] == 5000 and s["sales"][1] == 0


# ------------------------------------------------------------------ end to end (database)
@pytest.fixture()
def conn():
    import psycopg
    from dotenv import load_dotenv
    from backend import schema_ext
    load_dotenv()
    c = psycopg.connect(host=os.environ["PGHOST"], port=os.environ["PGPORT"], dbname=os.environ["PGDATABASE"],
                        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"], connect_timeout=20)
    schema_ext.ensure(c)
    yield c
    c.rollback(); c.close()


def _seed_books(conn):
    bid = conn.execute("INSERT INTO businesses (whatsapp_phone, display_name) VALUES (%s,%s) RETURNING id",
                       (f"+9197{uuid.uuid4().int % 100_000_000:08d}", "Math Test Unit")).fetchone()[0]
    for i in range(10):
        y, m = (2026, 1 + i)
        conn.execute("INSERT INTO ledger_entries (business_id, entry_date, direction, amount_paise, category, counterparty, gst_rate_bp, source)"
                     " VALUES (%s,%s,'in',%s,'sales','C',1800,'manual')", (bid, date(y, m, 5), (100000 + 7000 * i) * 100))
        conn.execute("INSERT INTO ledger_entries (business_id, entry_date, direction, amount_paise, category, counterparty, gst_rate_bp, source)"
                     " VALUES (%s,%s,'out',%s,'purchases','S',1800,'manual')", (bid, date(y, m, 8), (60000 + 3000 * i) * 100))
    conn.commit()
    return bid


def test_math_agent_end_to_end_blocks_hostile_formulas_and_keeps_good_ones(conn):
    from backend.agents.math_agent import MathAgent
    bid = _seed_books(conn)
    model = FakeLLM({"formulas": [
        {"name": "evil", "expression": "__import__('os').system('x')", "kind": "descriptive", "target": None, "why": "x"},
        {"name": "sales over purchases", "expression": "sales / purchases", "kind": "descriptive", "target": None, "why": "markup"}]})
    out = MathAgent(conn, model, FakeLLM(text="- Your margin is fine.")).run(bid, (2026, 10), use_web=False)
    by = {r["expression"]: r for r in out["formulas"]}
    assert by["__import__('os').system('x')"]["status"] == "rejected"
    assert by["sales / purchases"]["status"] == "descriptive"
    assert out["insights"], "an insight should be written"




def test_market_range_needs_both_numbers_in_the_quote():
    page = "Blended shop-level margin typically lands at 8-12% in India."
    ok = FakeLLM({"facts": [{"metric": "margin", "low": 8, "high": 12, "unit": "%", "quote": "typically lands at 8-12% in India"}]})
    got = market.extract(ok, "trading", _hit(page))
    assert len(got) == 1 and got[0]["value"] == 8 and got[0]["value_high"] == 12
    bad = FakeLLM({"facts": [{"metric": "margin", "low": 8, "high": 20, "unit": "%", "quote": "typically lands at 8-12% in India"}]})
    assert market.extract(bad, "trading", _hit(page)) == []


def test_two_trending_series_do_not_look_predictive():
    """The old backtest called 'purchases predict sales' validated when both simply rose. The trend baseline stops that."""
    f = compile_formula("purchases", U)
    n = 14
    sales = 100000 + 7000 * np.arange(n)
    purchases = 60000 + 2500 * np.arange(n)
    ev = backtest.evaluate_predictive(f, _series(n, sales, purchases), "sales", n, n_candidates=3)
    assert ev.status == "rejected", ev


def test_insight_sentences_come_from_templates_not_the_model(conn):
    from backend.agents.math_agent import MathAgent
    bid = _seed_books(conn)
    writer = FakeLLM(text="- Sales will reach Rs 9,99,999 next month, a significant and steady rise.")
    out = MathAgent(conn, FakeLLM({"formulas": []}), writer).run(bid, (2026, 10), use_web=False)
    body = out["insights"][0]["body"]
    assert "999" not in body and "significant" not in body.lower() and "steady" not in body.lower()
    assert "Gross margin" in body and "confirm them with your CA" in body


def test_a_judgemental_model_rationale_is_not_shown(conn):
    from backend.agents.math_agent import MathAgent
    bid = _seed_books(conn)
    model = FakeLLM({"formulas": [{"name": "Plain ratio of sales to purchases", "expression": "sales / purchases", "kind": "descriptive",
                                   "target": None, "why": "A strong and healthy sign of efficiency"}]})
    body = MathAgent(conn, model, FakeLLM()).run(bid, (2026, 10), use_web=False)["insights"][0]["body"]
    assert "Plain ratio of sales to purchases" in body and "healthy" not in body.lower() and "Model idea" not in body


# ------------------------------------------------------------------ reading library (retrieval only)
def test_library_parses_openstax_modules_and_skips_equations(tmp_path):
    from backend.analytics import library
    f = tmp_path / "index.cnxml"
    f.write_text('<document xmlns="http://cnx.rice.edu/cnxml" xmlns:m="http://www.w3.org/1998/Math/MathML"><title>Margins</title>'
                 '<content><para id="a">Gross margin shows the profit made before overheads are deducted from sales, which is a useful '
                 'first check on pricing. <m:math><m:mi>x</m:mi></m:math> More text follows here.</para></content></document>', encoding="utf-8")
    chunks = library.module_chunks(f)
    assert chunks and chunks[0][0] == "Margins" and "Gross margin shows" in chunks[0][1] and "x" not in chunks[0][1].split("More")[0][-5:]


def test_library_hides_non_commercial_books_when_switched_off(conn, monkeypatch):
    from backend.analytics import library
    tag = "zqxlibtest" + uuid.uuid4().hex[:6]
    conn.execute("INSERT INTO library_chunks (book, section, text, license, nc, source_url, attribution) VALUES "
                 "('Test Book','S',%s,'CC BY-NC-SA 4.0',TRUE,'https://example.org','Test attribution')", (f"A definition about {tag} for testing.",))
    conn.commit()
    try:
        monkeypatch.setenv("LIBRARY_ALLOW_NC", "1")
        assert library.search(conn, tag)
        monkeypatch.setenv("LIBRARY_ALLOW_NC", "0")
        assert library.search(conn, tag) == []
    finally:
        conn.execute("DELETE FROM library_chunks WHERE book='Test Book'")
        conn.commit()


def test_repair_round_fixes_a_broken_formula_using_the_checkers_error(conn):
    from backend.agents.math_agent import MathAgent

    class Scripted:
        def __init__(self):
            self.calls = 0

        def json_call(self, system, user, **k):
            self.calls += 1
            if self.calls == 1:
                return {"formulas": [{"name": "Growth", "expression": "growth(sales, 1)", "kind": "descriptive", "target": None, "why": "x"}]}
            assert "growth() takes 1 argument" in user          # the checker's message reached the model
            return {"formulas": [{"name": "Growth", "expression": "growth(sales)", "kind": "descriptive", "target": None, "why": "x"}]}

    agent = MathAgent(None, math_llm=Scripted())
    months, s = [(2026, i) for i in range(1, 9)], {k: np.arange(1, 9, dtype=float) for k in U}
    out = agent.propose(U, months, s)
    assert [c["expression"] for c in out] == ["growth(sales)"]
