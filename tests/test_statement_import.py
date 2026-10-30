import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from statement_import import mask_statement  # noqa: E402

# Different bank's header format + the kinds of PII real statements carry
SAMPLE = """Txn Date,Description,Withdrawal Amt,Deposit Amt,Balance
01/08/2026,NEFT-SALARY-ACME TECH PVT LTD-ACCT 001234567890,,"50,000.00","62,000.00"
02/08/2026,UPI-ananya.r@okicici-Ananya R-REF 512398765432,0.00,660.00,62660.00
03/08/2026,CARD-PULSE CLUB XXXX4321,2440.00,0.00,60220.00
04/08/2026,garbage row,abc,,
"""


def test_only_necessary_columns_survive(tmp_path):
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    src.write_text(SAMPLE, encoding="utf-8")
    receipt = mask_statement(src, dst)
    text = dst.read_text(encoding="utf-8")

    assert text.splitlines() == [
        "date,category,debit,credit,balance",  # the running balance stays: Orbit's current balance is the last one
        "2026-08-01,Income,,50000,62000",
        "2026-08-02,Friends (split-back),,660,62660",
        "2026-08-03,Club,2440,,60220",
    ]
    for secret in ("ACME", "Ananya", "okicici", "1234567890", "512398765432", "4321"):
        assert secret not in text
    assert receipt["rejected"] == [{"line": 5, "reason": "could not convert string to float: 'abc'"}]
    assert receipt["dropped_columns"] == ["Description"]


def test_sample_statement_keeps_the_briefs_numbers(tmp_path):
    # data/samples/manu_statement.csv: 9 Jul - 8 Oct. Its Aug-Sep is the team brief's statement, unchanged.
    receipt = mask_statement(ROOT / "data" / "samples" / "manu_statement.csv", tmp_path / "out.csv")
    assert (receipt["rows_kept"], receipt["rejected"], receipt["dropped_columns"]) == (245, [], ["Narration", "Mode"])
    with open(tmp_path / "out.csv", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["date"][:7] in ("2026-08", "2026-09")]
    assert "Uncategorized" not in {r["category"] for r in rows}
    assert rows[-1]["balance"] == "21842"  # 30 Sep, as in the brief
    months = 2
    fixed = {"Rent (PG, incl. food)", "Investments (SIP)", "Subscriptions", "Phone"}

    def spend(cats=None):
        return sum(float(r["debit"]) for r in rows if r["debit"] and (cats is None or r["category"] in cats))

    assert spend() / months == 46319.5  # brief: "about 46,300"
    assert spend(fixed) / months == 15617  # brief: "about 15,600"


RAW = ROOT / "data" / "raw"


@pytest.mark.skipif(not (RAW / "manu_statement_raw.csv").exists(), reason="raw statements are never in git")
def test_rules_match_ground_truth(tmp_path):
    from_rules, from_truth = tmp_path / "rules.csv", tmp_path / "truth.csv"
    mask_statement(RAW / "manu_statement_raw.csv", from_rules)
    mask_statement(RAW / "manu_statement_categorized.csv", from_truth)
    assert from_rules.read_text(encoding="utf-8") == from_truth.read_text(encoding="utf-8")
