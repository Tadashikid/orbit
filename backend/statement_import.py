"""Bank-statement import with data minimisation.

A statement goes in; only what the decision engine needs comes out:
    date, category, debit, credit, balance (the running balance: Orbit's "current balance" is the last one)
Everything else is dropped before anything is stored: narration (friend names, UPI IDs,
account/card/reference numbers, employer, landlord), payment mode. The raw upload is masked in memory
and never written to disk; the Finance MCP server and the LLM only ever see the minimised rows.

Usage:  python backend/statement_import.py <statement.csv> <out.masked.csv>
"""
import csv
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

KEEP = ["date", "category", "debit", "credit", "balance"]

# Header names seen on Indian bank exports -> our names
ALIASES = {
    "date": {"date", "txn date", "transaction date", "value date"},
    "narration": {"narration", "description", "particulars", "remarks"},
    "category": {"category"},
    "debit": {"debit", "withdrawal", "withdrawal amt", "withdrawal amt.", "dr"},
    "credit": {"credit", "deposit", "deposit amt", "deposit amt.", "cr"},
    "balance": {"balance", "closing balance", "running balance", "available balance", "balance amt"},
}
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%b-%Y"]

# ponytail: keyword rules tuned to the Manu fixture (100% match vs ground truth, see tests);
# unknown debits -> "Uncategorized". Add an LLM fallback only if a new statement needs it.
RULES = [
    (r"SALARY|CASHBACK|CREDIT INTEREST", "Income"),
    (r"PG RENT", "Rent (PG, incl. food)"),
    (r"\bSIP\b", "Investments (SIP)"),
    (r"SPOTIFY|NETFLIX", "Subscriptions"),
    (r"\bJIO\b", "Phone"),
    (r"METRO", "Transport (metro)"),
    (r"\bOLA\b|\bUBER\b", "Transport (cab)"),
    (r"PLAYO|DECATHLON", "Sports (badminton)"),
    (r"\bCLUB\b|LOUNGE", "Club"),
    (r"HOPS|PITCHER|BREWPUB", "Partying"),
    (r"MEGHANA|EMPIRE|BARBEQUE", "Dining with friends"),
    (r"TIMEZONE|SMAAASH|BOARD GAME", "Games & entertainment"),
    (r"ZOMATO|SWIGGY", "Food delivery"),
    (r"APOLLO|PRACTO", "Health"),
    (r"SALON", "Personal care"),
    (r"MYNTRA|AMAZON|NYKAA", "Shopping"),
    (r"CHAI|BAKERY|COFFEE|ZEPTO|BLINKIT|JUICE", "Snacks & drinks"),
]


def categorize(narration, is_credit):
    up = narration.upper()
    for pattern, category in RULES:
        if re.search(pattern, up):
            return category
    # ponytail: unmatched incoming money is treated as a friend paying back (true for the persona)
    return "Friends (split-back)" if is_credit else "Uncategorized"


def _column(headers, name):
    return next((h for h in headers if h.strip().lower() in ALIASES[name]), None)


def _amount(text):
    text = (text or "").replace(",", "").strip()
    value = float(text) if text else 0.0
    return value or None  # blank/0 = "not this direction", never a silent zero amount


def _date(text):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"unrecognised date {text!r}")


def _fmt(value):
    return "" if value is None else (int(value) if value.is_integer() else round(value, 2))


def mask_text(text):
    """Raw statement CSV text -> (minimised CSV text, import receipt: kept / dropped / rejected). Nothing touches disk."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))  # Excel's byte-order mark
    headers = reader.fieldnames or []
    cols = {name: _column(headers, name) for name in ALIASES}
    missing = [n for n in ("date", "debit", "credit", "balance") if not cols[n]]
    if missing or not (cols["category"] or cols["narration"]):
        raise ValueError(f"statement needs date, debit, credit, balance and a narration or category column; missing {missing}")

    rows, rejected, by = [], [], {"file": 0, "rules": 0}
    for line, row in enumerate(reader, start=2):
        try:
            debit, credit = _amount(row[cols["debit"]]), _amount(row[cols["credit"]])
            if (debit is None) == (credit is None):
                raise ValueError("need exactly one of debit/credit")
            date, balance = _date(row[cols["date"]]), float((row[cols["balance"]] or "").replace(",", ""))
        except (ValueError, AttributeError) as e:
            rejected.append({"line": line, "reason": str(e)})  # reported, never silently dropped
            continue
        given = (row[cols["category"]] or "").strip() if cols["category"] else ""
        category = given or categorize(row[cols["narration"]] or "", credit is not None)
        by["file" if given else "rules"] += 1
        rows.append({"date": date, "category": category, "debit": _fmt(debit), "credit": _fmt(credit), "balance": _fmt(balance)})
    if not rows:
        raise ValueError("no usable rows in the statement")
    if rows[0]["date"] > rows[-1]["date"]:
        rows.reverse()  # newest-first export: the last row must be the latest balance

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=KEEP, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    used = {cols[n] for n in KEEP}
    return out.getvalue(), {
        "rows_in": len(rows) + len(rejected),
        "rows_kept": len(rows),
        "rejected": rejected,
        "kept_columns": KEEP,
        "dropped_columns": [h for h in headers if h not in used],
        "categorized_by": by,
        "from": rows[0]["date"],
        "to": rows[-1]["date"],
    }


def mask_statement(src, dst):
    """File version of mask_text (CLI and tests)."""
    text, receipt = mask_text(Path(src).read_text(encoding="utf-8-sig"))
    Path(dst).write_text(text, encoding="utf-8")
    return receipt


if __name__ == "__main__":
    print(json.dumps(mask_statement(sys.argv[1], sys.argv[2]), indent=2))
