"""Finance MCP server on :8103 (streamable HTTP at /mcp).

No bank access. Everything comes from the bank statement the user uploads in the Orbit app, already MASKED by
the backend (date, category, debit, credit, balance only; narration and mode never reach this server).
  balance   the running balance on the statement's last row
  forecast  recurring items (salary, rent, SIPs, bills) + everyday spending per category per weekday, back-tested
Run:  .venv\\Scripts\\python mcp_servers\\finance_server.py
"""
import csv
import io
import json
import os
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

DATA = Path(__file__).resolve().parents[1] / "data"
# The session's statement (gitignored). ORBIT_STATEMENT points tests at their own copy.
STATEMENT = Path(os.getenv("ORBIT_STATEMENT") or DATA / "session" / "statement.csv")
COST_TABLE = DATA / "cost_table.json"
COLUMNS = ["date", "category", "debit", "credit", "balance"]  # = statement_import.KEEP
RECENT_DAYS = 28  # the spending "level": what you've spent on each category lately
TREND_CLIP = (0.5, 2.0)  # one big purchase can at most double a category's forecast
BACKTEST_DAYS = 28
READ = ToolAnnotations(readOnlyHint=True)

mcp = FastMCP("finance", port=8103 + int(os.getenv("ORBIT_PORT_OFFSET", "0")))  # tests use their own ports


def _rows():
    """(date, category, amount, is_income, balance) for every statement row, oldest first."""
    if not STATEMENT.exists():
        raise ValueError("No bank statement uploaded yet: upload one in the Orbit app")
    with open(STATEMENT, encoding="utf-8") as f:
        rows = [(date.fromisoformat(r["date"]), r["category"], float(r["debit"] or r["credit"]), not r["debit"], float(r["balance"]))
                for r in csv.DictReader(f)]
    return sorted(rows, key=lambda r: r[0])  # stable: same-day rows keep the bank's order, so the last balance is the latest


def _recurring(rows):
    """Salary, rent, SIPs, bills: the same category and amount, about a month apart, every month of the statement."""
    span = (rows[-1][0] - rows[0][0]).days + 1
    need = 3 if span >= 85 else 2  # ponytail: a day-31 bill shows only twice in 3 months; add day tolerance if one matters
    seen = defaultdict(list)
    for d, cat, amt, income, _ in rows:
        seen[(cat, amt, income)].append(d)
    found = []
    for (cat, amt, income), days in seen.items():
        if len(days) >= need and all(25 <= (b - a).days <= 35 for a, b in zip(days, days[1:])):
            day = Counter(d.day for d in days).most_common(1)[0][0]  # rent paid on the 5th or 6th -> the usual day
            found.append({"category": cat, "day_of_month": day, "amount": amt, "type": "income" if income else "debit"})
    return sorted(found, key=lambda r: r["day_of_month"])


def _rates(rows, recurring, end, weekly=True):
    """Everyday spending forecast: Rs per day for each category on each weekday (Mon..Sun), whole rupees.
    weekly: your weekday pattern over the whole statement (club on Sundays, badminton on Tuesdays) x how much you've
    spent on that category in the last RECENT_DAYS compared with your average (spending creeping up or down).
    Otherwise the plain daily average per category, the same every day."""
    fixed = {(r["category"], r["amount"], r["type"] == "income") for r in recurring}
    days = [rows[0][0] + timedelta(days=i) for i in range((end - rows[0][0]).days + 1)]
    recent_days = min(RECENT_DAYS, len(days))
    per_weekday = Counter(d.weekday() for d in days)
    by_weekday, total, recent = defaultdict(lambda: [0.0] * 7), defaultdict(float), defaultdict(float)
    for d, cat, amt, income, _ in rows:
        if income or d > end or (cat, amt, income) in fixed:
            continue
        by_weekday[cat][d.weekday()] += amt
        total[cat] += amt
        if d > end - timedelta(days=recent_days):
            recent[cat] += amt
    rates = {}
    for cat, sums in by_weekday.items():
        if not weekly:
            rates[cat] = [round(total[cat] / len(days))] * 7
            continue
        trend = min(max((recent[cat] / recent_days) / (total[cat] / len(days)), TREND_CLIP[0]), TREND_CLIP[1])
        rates[cat] = [round(s / per_weekday[k] * trend) if per_weekday[k] else 0 for k, s in enumerate(sums)]
    return dict(sorted(rates.items(), key=lambda x: -sum(x[1])))


def _backtest(rows, recurring):
    """Fit both forecasts on everything but the last 4 weeks, forecast those 4 weeks, compare with what was really
    spent, and choose the one that missed less. A light spender's few outings are noise, not a weekly pattern, so
    the weekday model has to earn its place on each statement. Miss = average error over every 3-day stretch
    (the horizon of "can I afford X this weekend")."""
    split = rows[-1][0] - timedelta(days=BACKTEST_DAYS)
    if (split - rows[0][0]).days + 1 < BACKTEST_DAYS:
        return None  # needs 4 weeks to learn from and 4 to test on
    fixed = {(r["category"], r["amount"], r["type"] == "income") for r in recurring}
    actual = Counter()
    for d, cat, amt, income, _ in rows:
        if d > split and not income and (cat, amt, income) not in fixed:
            actual[d] += amt
    test = [split + timedelta(days=i) for i in range(1, BACKTEST_DAYS + 1)]
    spans = [test[i:i + 3] for i in range(len(test) - 2)]
    result = {"days": BACKTEST_DAYS}
    for name, weekly in (("weekday", True), ("flat", False)):
        rates = _rates(rows, recurring, split, weekly)
        model = {d: sum(r[d.weekday()] for r in rates.values()) for d in test}
        result[f"{name}_miss_per_3_days"] = round(sum(abs(sum(model[d] for d in s) - sum(actual[d] for d in s)) for s in spans) / len(spans))
        result[f"{name}_vs_actual_pct"] = round((sum(model.values()) / sum(actual.values()) - 1) * 100, 1) if actual else None
    result["chosen"] = "weekday" if result["weekday_miss_per_3_days"] < result["flat_miss_per_3_days"] else "flat"
    return result


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
def load_statement(statement: str) -> dict:
    """Replace this session's bank statement with a MASKED one (CSV columns exactly: date,category,debit,credit,balance).
    Write tool: only the user's own upload in the Orbit app may call it, never the AI."""
    if len(statement) > 2_000_000:
        raise ValueError("statement too large (2 MB max)")
    reader = csv.DictReader(io.StringIO(statement))
    if reader.fieldnames != COLUMNS:
        raise ValueError(f"expected a masked statement with columns {','.join(COLUMNS)}")
    rows = []
    for line, r in enumerate(reader, start=2):
        try:
            date.fromisoformat(r["date"])
            debit, credit, _ = float(r["debit"] or 0), float(r["credit"] or 0), float(r["balance"])
            if (debit > 0) == (credit > 0) or not 0 < len(r["category"]) <= 60:
                raise ValueError("need a category and exactly one positive debit or credit")
        except (ValueError, TypeError) as e:
            raise ValueError(f"line {line}: {e}") from None
        rows.append(r)
    if not rows:
        raise ValueError("the statement has no rows")
    STATEMENT.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATEMENT.with_suffix(".tmp")
    tmp.write_text(statement, encoding="utf-8")
    tmp.replace(STATEMENT)
    return {"success": True, "rows": len(rows), **get_balance(), "from": _rows()[0][0].isoformat()}


@mcp.tool(annotations=READ)
def get_balance() -> dict:
    """Current bank balance: the running balance on the last row of the uploaded statement. Orbit has no bank access."""
    d, *_, balance = _rows()[-1]
    return {"balance": balance, "currency": "INR", "as_of": d.isoformat(), "source": "statement_csv"}


@mcp.tool(annotations=READ)
def get_sips() -> dict:
    """Recurring SIP investments found in the statement: amount and day of month."""
    rows = _rows()
    months = defaultdict(set)
    for d, cat, amt, income, _ in rows:
        if cat == "Investments (SIP)" and not income:
            months[(amt, d.day)].add(d.strftime("%Y-%m"))
    sips = [{"amount": a, "day_of_month": day, "months_seen": len(m)} for (a, day), m in sorted(months.items(), key=lambda x: x[0][1])]
    return {"sips": sips, "monthly_total": sum(s["amount"] for s in sips), "source": "statement_csv", "as_of": rows[-1][0].isoformat()}


@mcp.tool(annotations=READ)
def get_spending_summary(days: int = 30) -> dict:
    """Spending by category over the last `days` days of the statement, monthly averages, and the forecast model:
    recurring items (salary, rent, SIPs, bills) and everyday spending per category per weekday, with its back-test."""
    if not 1 <= days <= 366:
        raise ValueError("days must be between 1 and 366")
    rows = _rows()
    start, end = rows[0][0], rows[-1][0]
    span = (end - start).days + 1
    window, monthly = defaultdict(float), defaultdict(float)
    for d, cat, amt, income, _ in rows:
        if not income:
            monthly[cat] += amt / span * 30.44  # prorated: a statement can start and end mid-month
            if d > end - timedelta(days=days):
                window[cat] += amt
    recurring = _recurring(rows)
    backtest = _backtest(rows, recurring)
    weekly = bool(backtest) and backtest["chosen"] == "weekday"  # untested (under 8 weeks of data) -> the simple average
    by_size = lambda d: {c: round(v, 2) for c, v in sorted(d.items(), key=lambda x: -x[1])}  # noqa: E731
    return {
        "period": {"from": max(start, end - timedelta(days=days - 1)).isoformat(), "to": end.isoformat(), "days": days},
        "total_spend": round(sum(window.values()), 2),
        "by_category": by_size(window),
        "monthly_avg_spend": round(sum(monthly.values()), 2),
        "monthly_avg_by_category": by_size(monthly),
        "monthly_commitments": sum(r["amount"] for r in recurring if r["type"] == "debit"),
        "recurring": recurring,
        "everyday_by_weekday": _rates(rows, recurring, end, weekly),
        "forecast": {"method": "your weekday pattern per category x your last 4 weeks" if weekly
                     else "your daily average per category (no steady weekly pattern to rely on)",
                     "trained_on": {"from": start.isoformat(), "to": end.isoformat(), "days": span},
                     "backtest": backtest},
        "source": "statement_csv",
        "as_of": end.isoformat(),
    }


@mcp.tool(annotations=READ)
def get_cost_table() -> dict:
    """User-editable cost estimates (low/high) for trip items such as stay, food and local transport."""
    return json.loads(COST_TABLE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
