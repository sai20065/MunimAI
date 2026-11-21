"""
Offline tests for the virtual-CA pieces that need no database: Tally and CSV import mapping, and
the auditor's rules against books with deliberately injected errors (a gold list).

Run (from munimai/):  python -m pytest eval/test_virtual_ca_offline.py -v
"""

from __future__ import annotations

from datetime import date

from backend.agents.auditor import audit_rows
from backend.connectors import csvimport, tally
from backend.connectors.base import snap_rate_bp

TALLY_XML = """<ENVELOPE><BODY><DATA><TALLYMESSAGE>
<VOUCHER VCHTYPE="Sales"><DATE>20261105</DATE><GUID>g-1</GUID><VOUCHERNUMBER>S-101</VOUCHERNUMBER>
 <PARTYLEDGERNAME>Anita Tailors</PARTYLEDGERNAME><PARTYGSTIN>29ABCDE1234F1Z5</PARTYGSTIN>
 <ALLLEDGERENTRIES.LIST><LEDGERNAME>Anita Tailors</LEDGERNAME><AMOUNT>-11800.00</AMOUNT></ALLLEDGERENTRIES.LIST>
 <ALLLEDGERENTRIES.LIST><LEDGERNAME>Sales</LEDGERNAME><AMOUNT>10000.00</AMOUNT></ALLLEDGERENTRIES.LIST>
 <ALLLEDGERENTRIES.LIST><LEDGERNAME>CGST 9%</LEDGERNAME><AMOUNT>900.00</AMOUNT></ALLLEDGERENTRIES.LIST>
 <ALLLEDGERENTRIES.LIST><LEDGERNAME>SGST 9%</LEDGERNAME><AMOUNT>900.00</AMOUNT></ALLLEDGERENTRIES.LIST>
</VOUCHER>
<VOUCHER VCHTYPE="Purchase"><DATE>20261107</DATE><GUID>g-2</GUID><VOUCHERNUMBER>P-7</VOUCHERNUMBER>
 <PARTYLEDGERNAME>Mysore Silk Traders</PARTYLEDGERNAME>
 <ALLLEDGERENTRIES.LIST><LEDGERNAME>Mysore Silk Traders</LEDGERNAME><AMOUNT>5600.00</AMOUNT></ALLLEDGERENTRIES.LIST>
 <ALLLEDGERENTRIES.LIST><LEDGERNAME>CGST</LEDGERNAME><AMOUNT>-300.00</AMOUNT></ALLLEDGERENTRIES.LIST>
 <ALLLEDGERENTRIES.LIST><LEDGERNAME>SGST</LEDGERNAME><AMOUNT>-300.00</AMOUNT></ALLLEDGERENTRIES.LIST>
</VOUCHER>
<VOUCHER VCHTYPE="Journal"><DATE>20261110</DATE><GUID>g-3</GUID></VOUCHER>
<VOUCHER VCHTYPE="Sales"><DATE>20261111</DATE><GUID>g-4</GUID><PARTYLEDGERNAME>Odd Rate Co</PARTYLEDGERNAME>
 <ALLLEDGERENTRIES.LIST><LEDGERNAME>Odd Rate Co</LEDGERNAME><AMOUNT>-1000.00</AMOUNT></ALLLEDGERENTRIES.LIST>
 <ALLLEDGERENTRIES.LIST><LEDGERNAME>CGST</LEDGERNAME><AMOUNT>200.00</AMOUNT></ALLLEDGERENTRIES.LIST>
</VOUCHER>
</TALLYMESSAGE></DATA></BODY></ENVELOPE>"""


def test_tally_maps_sales_purchases_and_skips_journals():
    entries, info = tally.parse_vouchers(TALLY_XML)
    assert info["vouchers_imported"] == 3
    assert info["skipped_by_type"] == {"Journal": 1}
    sale, purchase, odd = entries
    assert (sale.direction, sale.amount_paise, sale.gst_rate_bp) == ("in", 1_180_000, 1800)
    assert sale.invoice_no == "S-101" and sale.counterparty_gstin == "29ABCDE1234F1Z5"
    assert (purchase.direction, purchase.amount_paise, purchase.gst_rate_bp) == ("out", 560_000, 1200)
    assert odd.gst_rate_bp is None            # 20/80 = 25%, not a slab: must go to a human
    assert sale.external_ref == "tally:g-1"


def test_snap_rate():
    assert snap_rate_bp(180_000, 1_180_000) == 1800
    assert snap_rate_bp(0, 100_000) == 0
    assert snap_rate_bp(25_000, 100_000) is None


def test_csv_import_and_bad_rows():
    text = ("date,type,party,gstin,invoice_no,amount,gst_rate\n"
            "2026-11-03,sale,Anita,29AAAAA0000A1Z5,S1,11800,18\n"
            "05/11/2026,purchase,Silk,29BBBBB1111B1Z5,P1,5600,12\n"
            "2026-11-06,loan,Bank,,X,100,0\n")
    entries, info = csvimport.parse_books(text)
    assert info["rows_ok"] == 2 and len(info["rows_rejected"]) == 1
    assert entries[1].entry_date == date(2026, 11, 5) and entries[1].gst_rate_bp == 1200


def _row(i, d, direction, rupees, **kw):
    base = dict(id=i, entry_date=d, direction=direction, amount_paise=rupees * 100, category="sales" if direction == "in" else "purchases",
                counterparty="Party", gst_rate_bp=1800, needs_review=False, invoice_no=f"INV{i}", counterparty_gstin="29AAAAA0000A1Z5")
    base.update(kw)
    return base


def _rules(found):
    return {f.rule for f in found}


TODAY = date(2026, 12, 1)
D = date(2026, 11, 10)


def test_clean_books_have_no_serious_findings():
    rows = [_row(1, D, "in", 11800), _row(2, D, "out", 5900, counterparty="Silk")]
    b2 = [{"supplier_gstin": "29AAAAA0000A1Z5", "invoice_no": "INV2", "tax_paise": 90000}]
    found = audit_rows(rows, b2, TODAY)
    assert not [f for f in found if f.severity in ("warn", "critical")]


def test_gold_list_injected_errors_are_all_found():
    rows = [
        _row(1, D, "out", 5900, counterparty="Silk", invoice_no="P-1"),                        # duplicate pair
        _row(2, D, "out", 5900, counterparty="Silk", invoice_no="P-1"),
        _row(3, D, "out", 11800, counterparty="Ghost", invoice_no="G-9"),                      # not in 2B
        _row(4, D, "out", 2360, invoice_no=""),                                                # no invoice number
        _row(5, D, "out", 2360, counterparty_gstin="", invoice_no="N-5"),                      # no gstin
        _row(6, D, "in", 11800, category="cloth"), _row(7, D, "in", 5600, category="cloth", gst_rate_bp=1200),  # rate mix
        _row(8, date(2027, 1, 5), "in", 1000),                                                 # future dated
        _row(9, D, "in", 500, needs_review=True),                                              # awaiting review
        _row(10, D, "out", 3000, counterparty="Same", invoice_no=""), _row(11, D, "out", 3000, counterparty="Same", invoice_no=""),  # possible dup
    ]
    b2 = [{"supplier_gstin": "29AAAAA0000A1Z5", "invoice_no": "P-1", "tax_paise": 90000},
          {"supplier_gstin": "29AAAAA0000A1Z5", "invoice_no": "N-5", "tax_paise": 36000},
          {"supplier_gstin": "29ZZZZZ9999Z1Z5", "invoice_no": "MISSED-1", "tax_paise": 50000}]
    found = audit_rules = audit_rows(rows, b2, TODAY)
    got = _rules(found)
    gold = {"duplicate_invoice", "itc_not_in_2b", "itc_no_invoice_no", "rate_inconsistency",
            "future_dated", "awaiting_review", "possible_duplicate", "in_2b_not_in_books"}
    assert gold <= got, f"missed: {gold - got}"
    dup = next(f for f in found if f.rule == "duplicate_invoice")
    assert dup.severity == "critical" and dup.entry_ids == [1, 2]


def test_without_gstr2b_it_says_it_could_not_reconcile():
    found = audit_rows([_row(1, D, "out", 5900)], [], TODAY)
    assert "no_2b_loaded" in _rules(found) and "itc_not_in_2b" not in _rules(found)


def test_amount_mismatch_against_2b():
    rows = [_row(1, D, "out", 11800)]                       # books tax = 1800.00
    b2 = [{"supplier_gstin": "29AAAAA0000A1Z5", "invoice_no": "INV1", "tax_paise": 120000}]
    assert "itc_amount_mismatch" in _rules(audit_rows(rows, b2, TODAY))
