"""Fetch auditable, forward-adjusted daily bars without importing the GUI.

Usage: .venv\\Scripts\\python scripts\\fetch_backtest_data.py --as-of 2026-10-03
The as-of date is exclusive: intraday/incomplete bars are never included.
Eastmoney uses the same endpoint/field mapping as QuoteService. A symbol is
never assembled from different providers or different adjustment conventions.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import time

import requests


DEFAULT_SYMBOLS = [
    "sh688820", "sh688825", "sh603986", "sh688270",
    "hk01810", "sh688110", "sz300308", "sh688256",
]
URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
PROJECT = Path(__file__).resolve().parents[1]
SHANGHAI = timezone(timedelta(hours=8))


def normalize(code: str) -> str:
    code = code.lower().strip()
    if code.startswith("hk") and code[2:].isdigit():
        return "hk" + code[2:].zfill(5)
    if code.startswith(("sh", "sz")) and len(code) == 8 and code[2:].isdigit():
        return code
    if len(code) == 6 and code.isdigit():
        return ("sh" if code.startswith(("5", "6", "9")) else "sz") + code
    raise ValueError(f"Unsupported symbol: {code}")


def secid(code: str) -> str:
    return ("116." + code[2:]) if code.startswith("hk") else (("1." if code.startswith("sh") else "0.") + code[2:])


def fetch_eastmoney(code: str, before: date, output: Path, *, offline: bool = False) -> tuple[list[dict], dict]:
    params = {
        "secid": secid(code), "klt": "101", "fqt": "1", "lmt": "1000000",
        "beg": "19900101", "end": (before - timedelta(days=1)).strftime("%Y%m%d"),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }
    raw_path = output / "raw" / f"{code}-eastmoney.json"
    if offline and not raw_path.exists():
        raise ValueError(f"No saved Eastmoney response for {code}")
    last_error = None
    for attempt in range(3):
        try:
            if offline:
                payload = json.loads(raw_path.read_bytes())
            else:
                response = requests.get(URL, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=(8, 30))
                response.raise_for_status()
                # Parsing bytes avoids requests' text/plain charset guessing.
                payload = json.loads(response.content)
            data = payload.get("data") or {}
            if payload.get("rc") != 0 or not data.get("klines"):
                raise ValueError(f"Empty/error response rc={payload.get('rc')}")
            if not offline:
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            rows = []
            for text in data["klines"]:
                parts = text.split(",")
                if len(parts) < 11:
                    raise ValueError(f"Malformed daily row {text!r}")
                rows.append(dict(zip(
                    ["date", "open", "close", "high", "low", "volume", "amount", "amplitude", "change_pct", "change", "turnover"],
                    [parts[0]] + [float(item) for item in parts[1:11]],
                ), code=code, source="东方财富日K"))
            return rows, {
                "provider": "Eastmoney", "endpoint": URL, "request_params": params,
                "adjustment": "forward_adjusted", "adjustment_parameter": "fqt=1",
                "adjustment_basis": "Provider's current forward-adjustment factors; not a point-in-time adjustment database.",
                "name": data.get("name"), "provider_total_bars": data.get("dktotal"),
                "raw_file": str(raw_path.relative_to(output)),
                "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                "fetched_at": datetime.fromtimestamp(raw_path.stat().st_mtime, SHANGHAI).isoformat(timespec="seconds"),
                "retrieval": "saved_raw_response" if offline else "network",
                "market": "HK" if code.startswith("hk") else "CN",
                "currency": "HKD" if code.startswith("hk") else "CNY",
                "volume_unit": "provider native units; do not compare absolute volume across symbols",
                "completeness": "Requested full available history since 1990; first bar is not independently verified as IPO date.",
            }
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(attempt + 1)
    raise RuntimeError(f"Eastmoney failed for {code}: {last_error}")


def validate(rows: list[dict], before: date) -> tuple[list[dict], dict]:
    by_date: dict[str, dict] = {}
    invalid = []
    duplicates = []
    excluded_dates = []
    for row in rows:
        day = date.fromisoformat(row["date"])
        if day >= before:
            excluded_dates.append(row["date"])
            continue
        numeric = [row[key] for key in ("open", "high", "low", "close", "volume", "amount")]
        issue = None
        if not all(math.isfinite(value) for value in numeric):
            issue = "non-finite value"
        elif min(row[key] for key in ("open", "high", "low", "close")) <= 0:
            issue = "non-positive price"
        elif row["volume"] < 0 or row["amount"] < 0:
            issue = "negative volume/amount"
        elif row["high"] < max(row["open"], row["close"], row["low"]) or row["low"] > min(row["open"], row["close"], row["high"]):
            issue = "OHLC containment violated"
        if issue:
            invalid.append({"date": row["date"], "reason": issue})
            continue
        if row["date"] in by_date:
            duplicate = {"date": row["date"], "identical": by_date[row["date"]] == row}
            duplicates.append(duplicate)
            if not duplicate["identical"]:
                raise ValueError(f"Conflicting bars on {row['date']}")
            continue
        by_date[row["date"]] = row
    # Removing scattered invalid prices and joining the remaining dates would
    # create artificial multi-day "one-bar" returns. Keep only the contiguous
    # valid suffix; the complete provider response remains in raw/ for audit.
    last_invalid = max((item["date"] for item in invalid), default=None)
    pre_invalid_excluded = [key for key in by_date if last_invalid and key <= last_invalid]
    clean = [by_date[key] for key in sorted(by_date) if not last_invalid or key > last_invalid]
    gaps = []
    jumps = []
    for prior, current in zip(clean, clean[1:]):
        gap = (date.fromisoformat(current["date"]) - date.fromisoformat(prior["date"])).days
        if gap > 7:
            gaps.append({"from": prior["date"], "to": current["date"], "calendar_days": gap})
        change = current["close"] / prior["close"] - 1
        if abs(change) > 0.35:
            jumps.append({"date": current["date"], "close_to_close_pct": round(change * 100, 3)})
    return clean, {
        "raw_rows": len(rows), "valid_rows": len(clean), "invalid_rows": invalid,
        "last_invalid_date": last_invalid,
        "otherwise_valid_rows_excluded_before_last_invalid": len(pre_invalid_excluded),
        "invalid_history_policy": "Use only the valid suffix after the final invalid bar; never splice across removed invalid bars.",
        "duplicate_dates": duplicates, "excluded_incomplete_or_future_dates": excluded_dates,
        "zero_volume_dates": [row["date"] for row in clean if row["volume"] == 0],
        "gaps_over_7_calendar_days": gaps,
        "gap_interpretation": "May reflect exchange holidays or suspensions. Missing trading sessions cannot be determined without an independent security calendar.",
        "close_jumps_over_35pct": jumps,
        "jump_interpretation": "Review flags, not automatically invalid: IPO early sessions and HK have different price limits.",
        "short_history_under_250_bars": len(clean) < 250,
        "minimum_price": min((row["low"] for row in clean), default=None),
        "sub_unit_price_dates": [row["date"] for row in clean if row["low"] < 1],
        "return_quality_warning": "Current forward-adjusted prices are rounded and can become non-positive or near zero in old history. Arithmetic return calculations on such history are unreliable. Raw historical prices plus point-in-time corporate actions are required for an exact total-return simulation.",
    }


def fetch_symbol(code: str, before: date, output: Path, *, offline: bool = False) -> dict:
    try:
        raw_rows, metadata = fetch_eastmoney(code, before, output, offline=offline)
    except RuntimeError as exc:
        raw_rows, metadata = fetch_eastmoney(code, before, output, offline=True)
        metadata["network_refresh_error"] = str(exc)
    rows, quality = validate(raw_rows, before)
    if not rows:
        raise ValueError("No valid completed daily bars")
    metadata.update({
        "symbol": code, "as_of_exclusive": before.isoformat(),
        "first_date": rows[0]["date"], "last_date": rows[-1]["date"],
        "bars": len(rows), "quality": quality,
    })
    destination = output / f"{code}.json"
    destination.write_text(json.dumps({"metadata": metadata, "klines": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return dict(metadata, file=destination.name, sha256=hashlib.sha256(destination.read_bytes()).hexdigest(), status="ok")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="*", default=DEFAULT_SYMBOLS)
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(SHANGHAI).date(), help="Exclude this date and later (YYYY-MM-DD)")
    parser.add_argument("--output", type=Path, default=PROJECT / "build" / "backtest-data")
    parser.add_argument("--offline", action="store_true", help="Revalidate saved raw responses without downloading")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    symbols = list(dict.fromkeys(normalize(code) for code in args.symbols))
    manifest = {
        "generated_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "as_of_exclusive": args.as_of.isoformat(),
        "purpose": "Research/backtest only; no trading orders submitted.",
        "symbols": {},
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_symbol, code, args.as_of, output, offline=args.offline): code for code in symbols}
        for future in as_completed(futures):
            code = futures[future]
            try:
                record = future.result()
                print(f"{code}: {record['bars']} bars {record['first_date']} through {record['last_date']}", flush=True)
            except Exception as exc:
                record = {"symbol": code, "status": "failed", "error": str(exc)}
                print(f"{code}: FAILED {exc}", flush=True)
            manifest["symbols"][code] = record
    manifest["symbols"] = {code: manifest["symbols"][code] for code in symbols}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(any(item["status"] != "ok" for item in manifest["symbols"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
