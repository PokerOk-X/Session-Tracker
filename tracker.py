#!/usr/bin/env python3
# tracker.py
"""
PokerOK Session Tracker
- One-file script, standard library only.
- Commands: start, end, log, status, stats
- Stores completed sessions in sessions.csv
- Stores active session draft in active_session.json

Usage examples:
  python tracker.py start
  python tracker.py end
  python tracker.py log
  python tracker.py status
  python tracker.py stats
  python tracker.py stats --from 2025-12-01 --to 2025-12-31 --format cash
  python tracker.py --file my_sessions.csv start
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

POKER_ROOM = "PokerOK"
DEFAULT_CSV = "sessions.csv"
DEFAULT_ACTIVE = "active_session.json"

FORMATS = ("cash", "mtt", "spin")


# ---------------------------
# Helpers: input + validation
# ---------------------------

def _print_err(msg: str) -> None:
    print(f"[!] {msg}", file=sys.stderr)


def prompt_str(label: str, default: Optional[str] = None, allow_empty: bool = False) -> str:
    while True:
        if default is not None:
            raw = input(f"{label} [{default}]: ").strip()
            if raw == "":
                raw = default
        else:
            raw = input(f"{label}: ").strip()

        if raw == "" and not allow_empty:
            _print_err("Пустое значение не допускается. Попробуйте снова.")
            continue
        return raw


def prompt_choice(label: str, choices: Tuple[str, ...], default: Optional[str] = None) -> str:
    choices_str = "/".join(choices)
    while True:
        raw = prompt_str(f"{label} ({choices_str})", default=default)
        raw_l = raw.strip().lower()
        if raw_l in choices:
            return raw_l
        _print_err(f"Неверный выбор. Допустимо: {choices_str}")


def prompt_float(label: str, default: Optional[float] = None, min_value: Optional[float] = 0.0) -> float:
    while True:
        if default is not None:
            raw = input(f"{label} [{default}]: ").strip()
            if raw == "":
                val = float(default)
                if min_value is not None and val < min_value:
                    _print_err(f"Значение должно быть >= {min_value}")
                    continue
                return val
        else:
            raw = input(f"{label}: ").strip()

        try:
            val = float(raw.replace(",", "."))
        except ValueError:
            _print_err("Введите число (например 123.45).")
            continue

        if min_value is not None and val < min_value:
            _print_err(f"Значение должно быть >= {min_value}")
            continue
        return val


def prompt_int(label: str, default: Optional[int] = None, min_value: Optional[int] = 0) -> int:
    while True:
        if default is not None:
            raw = input(f"{label} [{default}]: ").strip()
            if raw == "":
                val = int(default)
                if min_value is not None and val < min_value:
                    _print_err(f"Значение должно быть >= {min_value}")
                    continue
                return val
        else:
            raw = input(f"{label}: ").strip()

        try:
            val = int(raw)
        except ValueError:
            _print_err("Введите целое число.")
            continue

        if min_value is not None and val < min_value:
            _print_err(f"Значение должно быть >= {min_value}")
            continue
        return val


def prompt_yes_no(label: str, default: bool = True) -> bool:
    d = "y" if default else "n"
    while True:
        raw = input(f"{label} (y/n) [{d}]: ").strip().lower()
        if raw == "":
            return default
        if raw in ("y", "yes", "д", "да"):
            return True
        if raw in ("n", "no", "н", "нет"):
            return False
        _print_err("Введите y или n.")


def parse_date_yyyy_mm_dd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_time_hh_mm(s: str) -> Tuple[int, int]:
    t = datetime.strptime(s, "%H:%M").time()
    return t.hour, t.minute


def iso_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def dt_from_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


def duration_minutes(start_iso: str, end_iso: str) -> int:
    s = dt_from_iso(start_iso)
    e = dt_from_iso(end_iso)
    mins = int(round((e - s).total_seconds() / 60))
    return max(mins, 0)


def safe_div(a: float, b: float) -> Optional[float]:
    if b == 0:
        return None
    return a / b


def fmt_money(x: Optional[float], currency: str = "") -> str:
    if x is None:
        return "-"
    cur = f" {currency}" if currency else ""
    return f"{x:.2f}{cur}"


def fmt_float(x: Optional[float], nd: int = 2, suffix: str = "") -> str:
    if x is None:
        return "-"
    return f"{x:.{nd}f}{suffix}"


def fmt_duration(mins: int) -> str:
    h = mins // 60
    m = mins % 60
    return f"{h}h {m:02d}m"


# ---------------------------
# Storage: active session + csv
# ---------------------------

def load_active(active_path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(active_path):
        return None
    try:
        with open(active_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _print_err(f"Не удалось прочитать активную сессию: {e}")
        return None


def save_active(active_path: str, data: Dict[str, Any]) -> None:
    with open(active_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clear_active(active_path: str) -> None:
    try:
        if os.path.exists(active_path):
            os.remove(active_path)
    except Exception as e:
        _print_err(f"Не удалось удалить active-session файл: {e}")


CSV_FIELDS = [
    # General
    "id",
    "poker_room",
    "format",
    "stake",
    "currency",
    "start_ts",
    "end_ts",
    "duration_min",
    "bankroll_start",
    "bankroll_end",
    "profit",
    "tables",
    "note",
    # Cash-specific
    "hands",
    "bb_value",
    "bb_profit",
    "bb_per_100",
    # MTT/Spin-specific
    "buyin_total",
    "prize_total",
    "roi",
]


def ensure_csv(csv_path: str) -> None:
    if os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
        return
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()


def append_row(csv_path: str, row: Dict[str, Any]) -> None:
    ensure_csv(csv_path)
    # Ensure all fields exist
    out = {k: row.get(k, "") for k in CSV_FIELDS}
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writerow(out)


def read_rows(csv_path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
        return []
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            return list(r)
    except Exception as e:
        _print_err(f"Не удалось прочитать CSV: {e}")
        return []


# ---------------------------
# Computations
# ---------------------------

def compute_metrics(session: Dict[str, Any]) -> Dict[str, Any]:
    """Mutates and returns the dict with computed metrics."""
    fmt = session.get("format", "").lower()
    currency = session.get("currency", "") or ""

    # duration
    if session.get("duration_min") in ("", None):
        if session.get("start_ts") and session.get("end_ts"):
            session["duration_min"] = duration_minutes(session["start_ts"], session["end_ts"])

    # profit
    # For MTT/Spin, if buyin/prize provided -> profit = prize - buyin
    buyin = _to_float(session.get("buyin_total"))
    prize = _to_float(session.get("prize_total"))
    br_s = _to_float(session.get("bankroll_start"))
    br_e = _to_float(session.get("bankroll_end"))

    if fmt in ("mtt", "spin") and buyin is not None and prize is not None:
        session["profit"] = round(prize - buyin, 2)
        # sanity check: if bankroll deltas exist, we can keep them but don't overwrite
        # (user may have added deposits/withdrawals etc.)
    else:
        if br_s is not None and br_e is not None:
            session["profit"] = round(br_e - br_s, 2)

    # Cash: bb metrics if possible
    if fmt == "cash":
        hands = _to_int(session.get("hands"))
        bb_value = _to_float(session.get("bb_value"))
        profit = _to_float(session.get("profit"))
        if profit is not None and bb_value is not None and bb_value > 0:
            bb_profit = profit / bb_value
            session["bb_profit"] = round(bb_profit, 2)
            if hands is not None and hands > 0:
                session["bb_per_100"] = round((bb_profit / hands) * 100.0, 2)

    # MTT/Spin ROI if possible
    if fmt in ("mtt", "spin"):
        profit = _to_float(session.get("profit"))
        if buyin is not None and buyin > 0 and profit is not None:
            session["roi"] = round((profit / buyin) * 100.0, 2)

    # Normalize empties
    for k in ("tables", "hands"):
        if session.get(k) is None:
            session[k] = ""
    for k in ("bb_value", "bb_profit", "bb_per_100", "buyin_total", "prize_total", "roi"):
        if session.get(k) is None:
            session[k] = ""

    # Ensure currency always string
    session["currency"] = currency
    return session


def _to_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def _to_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).replace(",", ".")))
    except ValueError:
        return None


# ---------------------------
# Command implementations
# ---------------------------

def cmd_start(args: argparse.Namespace) -> int:
    active = load_active(args.active)
    if active:
        _print_err("У вас уже есть активная сессия. Завершите её командой: python tracker.py end")
        _print_err(f"Или удалите файл: {args.active} (если он некорректный).")
        return 2

    print("=== PokerOK Session Tracker: START ===")
    fmt = prompt_choice("Формат", FORMATS, default="cash")
    stake = prompt_str("Лимит/бай-ин (пример: NL10, 5$, 10$+1$)")
    currency = prompt_str("Валюта (опционально, напр. USD/EUR)", default="", allow_empty=True).upper()
    bankroll_start = prompt_float("Банкролл на старте", min_value=0.0)
    tables = None
    if prompt_yes_no("Указать количество столов?", default=False):
        tables = prompt_int("Кол-во столов", min_value=1)
    note = prompt_str("Заметка (опционально)", default="", allow_empty=True)

    session = {
        "id": str(uuid.uuid4()),
        "poker_room": POKER_ROOM,
        "format": fmt,
        "stake": stake,
        "currency": currency,
        "start_ts": iso_now(),
        "end_ts": "",
        "duration_min": "",
        "bankroll_start": bankroll_start,
        "bankroll_end": "",
        "profit": "",
        "tables": tables if tables is not None else "",
        "note": note,
        "hands": "",
        "bb_value": "",
        "bb_profit": "",
        "bb_per_100": "",
        "buyin_total": "",
        "prize_total": "",
        "roi": "",
    }

    save_active(args.active, session)
    print("\nСессия начата ✅")
    print(f"Start time: {session['start_ts']}")
    print(f"Формат: {fmt} | Stake: {stake}")
    print(f"Файл активной сессии: {args.active}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    active = load_active(args.active)
    if not active:
        print("Активная сессия не найдена.")
        return 0

    print("=== PokerOK Session Tracker: STATUS ===")
    start_ts = active.get("start_ts", "")
    fmt = active.get("format", "")
    stake = active.get("stake", "")
    currency = active.get("currency", "")
    br_s = _to_float(active.get("bankroll_start"))
    tables = active.get("tables", "")
    note = active.get("note", "")

    now = datetime.now().replace(microsecond=0)
    try:
        start_dt = dt_from_iso(start_ts)
        mins = int(round((now - start_dt).total_seconds() / 60))
    except Exception:
        mins = 0

    print(f"Start: {start_ts}")
    print(f"Elapsed: {fmt_duration(max(mins, 0))}")
    print(f"Формат: {fmt} | Stake: {stake} | Валюта: {currency or '-'}")
    print(f"BR start: {fmt_money(br_s, currency)}")
    print(f"Tables: {tables or '-'}")
    print(f"Note: {note or '-'}")
    return 0


def cmd_end(args: argparse.Namespace) -> int:
    active = load_active(args.active)
    if not active:
        _print_err("Активная сессия не найдена. Сначала запустите: python tracker.py start")
        return 2

    print("=== PokerOK Session Tracker: END ===")
    fmt = (active.get("format") or "").lower()
    currency = active.get("currency", "") or ""
    print(f"Формат: {fmt} | Stake: {active.get('stake','')}")
    print(f"Start: {active.get('start_ts','')}")

    bankroll_end = prompt_float("Банкролл на финише", min_value=0.0)

    # Format-specific inputs
    if fmt == "cash":
        if prompt_yes_no("Указать количество сыгранных рук?", default=True):
            hands = prompt_int("Сыграно рук", min_value=0)
            active["hands"] = hands
        if prompt_yes_no("Указать стоимость 1 BB в валюте (нужно для bb/100)?", default=True):
            bb_value = prompt_float("BB value (например NL10 -> 0.10)", min_value=0.0)
            if bb_value == 0:
                _print_err("BB value не может быть 0. Метрики bb/100 не будут посчитаны.")
            else:
                active["bb_value"] = bb_value

    if fmt in ("mtt", "spin"):
        print("\nДля MTT/Spin можно указать buy-in total и prize total (чтобы посчитать ROI).")
        if prompt_yes_no("Ввести buy-in total и prize total?", default=True):
            buyin_total = prompt_float("Buy-in total (суммарные взносы)", min_value=0.0)
            prize_total = prompt_float("Prize total (суммарные призы)", min_value=0.0)
            active["buyin_total"] = buyin_total
            active["prize_total"] = prize_total

    note_end = prompt_str("Итоговая заметка (опционально)", default="", allow_empty=True)
    if note_end:
        base_note = active.get("note", "")
        active["note"] = (base_note + " | " if base_note else "") + note_end

    active["bankroll_end"] = bankroll_end
    active["end_ts"] = iso_now()

    # validate chronological
    try:
        if dt_from_iso(active["end_ts"]) <= dt_from_iso(active["start_ts"]):
            _print_err("Время окончания некорректно (end <= start).")
            return 2
    except Exception:
        pass

    session = compute_metrics(active)
    append_row(args.file, session)
    clear_active(args.active)

    print("\nСессия завершена ✅ и сохранена.")
    _print_session_receipt(session)
    print(f"\nЗаписано в: {args.file}")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    print("=== PokerOK Session Tracker: LOG (one-shot) ===")
    fmt = prompt_choice("Формат", FORMATS, default="cash")
    stake = prompt_str("Лимит/бай-ин (пример: NL10, 5$, 10$+1$)")
    currency = prompt_str("Валюта (опционально, напр. USD/EUR)", default="", allow_empty=True).upper()

    # Date and time
    dflt_date = date.today().strftime("%Y-%m-%d")
    session_date = prompt_str("Дата (YYYY-MM-DD)", default=dflt_date)
    try:
        d = parse_date_yyyy_mm_dd(session_date)
    except Exception:
        _print_err("Неверная дата. Используйте формат YYYY-MM-DD.")
        return 2

    # Choose either start/end time or duration
    use_times = prompt_yes_no("Указать start/end время (иначе введёте duration)?", default=True)
    if use_times:
        st = prompt_str("Start time (HH:MM)", default="12:00")
        en = prompt_str("End time (HH:MM)", default="14:00")
        try:
            sh, sm = parse_time_hh_mm(st)
            eh, em = parse_time_hh_mm(en)
        except Exception:
            _print_err("Неверный формат времени. Используйте HH:MM.")
            return 2

        start_dt = datetime(d.year, d.month, d.day, sh, sm, 0)
        end_dt = datetime(d.year, d.month, d.day, eh, em, 0)

        # If end earlier than start, assume it crossed midnight
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

        start_ts = start_dt.isoformat()
        end_ts = end_dt.isoformat()
        dur_min = duration_minutes(start_ts, end_ts)
    else:
        dur_min = prompt_int("Duration minutes", default=120, min_value=1)
        # pick an end time "now" but store date; we can store start_ts = end - duration
        end_dt = datetime.now().replace(microsecond=0)
        start_dt = end_dt - timedelta(minutes=dur_min)
        start_ts = start_dt.isoformat()
        end_ts = end_dt.isoformat()

    bankroll_start = prompt_float("Банкролл на старте", min_value=0.0)
    bankroll_end = prompt_float("Банкролл на финише", min_value=0.0)

    tables = ""
    if prompt_yes_no("Указать количество столов?", default=False):
        tables = str(prompt_int("Кол-во столов", min_value=1))

    note = prompt_str("Заметка (опционально)", default="", allow_empty=True)

    session = {
        "id": str(uuid.uuid4()),
        "poker_room": POKER_ROOM,
        "format": fmt,
        "stake": stake,
        "currency": currency,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "duration_min": dur_min,
        "bankroll_start": bankroll_start,
        "bankroll_end": bankroll_end,
        "profit": "",
        "tables": tables,
        "note": note,
        "hands": "",
        "bb_value": "",
        "bb_profit": "",
        "bb_per_100": "",
        "buyin_total": "",
        "prize_total": "",
        "roi": "",
    }

    if fmt == "cash":
        if prompt_yes_no("Указать количество рук?", default=True):
            session["hands"] = prompt_int("Сыграно рук", min_value=0)
        if prompt_yes_no("Указать BB value (нужно для bb/100)?", default=True):
            bb_value = prompt_float("BB value (например NL10 -> 0.10)", min_value=0.0)
            if bb_value > 0:
                session["bb_value"] = bb_value

    if fmt in ("mtt", "spin"):
        if prompt_yes_no("Ввести buy-in total и prize total (чтобы посчитать ROI)?", default=True):
            session["buyin_total"] = prompt_float("Buy-in total", min_value=0.0)
            session["prize_total"] = prompt_float("Prize total", min_value=0.0)

    session = compute_metrics(session)
    append_row(args.file, session)

    print("\nЗапись сохранена ✅")
    _print_session_receipt(session)
    print(f"\nЗаписано в: {args.file}")
    return 0


def _print_session_receipt(session: Dict[str, Any]) -> None:
    fmt = session.get("format", "")
    currency = session.get("currency", "") or ""
    profit = _to_float(session.get("profit"))
    dur = _to_int(session.get("duration_min")) or 0

    print("\n--- SESSION SUMMARY ---")
    print(f"Room: {session.get('poker_room','')}")
    print(f"Format: {fmt} | Stake: {session.get('stake','')}")
    print(f"Start: {session.get('start_ts','')}")
    print(f"End:   {session.get('end_ts','')}")
    print(f"Duration: {fmt_duration(dur)}")
    print(f"BR: {fmt_money(_to_float(session.get('bankroll_start')), currency)} -> {fmt_money(_to_float(session.get('bankroll_end')), currency)}")
    print(f"Profit: {fmt_money(profit, currency)}")

    if fmt == "cash":
        hands = _to_int(session.get("hands"))
        bb100 = _to_float(session.get("bb_per_100"))
        bbv = _to_float(session.get("bb_value"))
        if hands is not None:
            print(f"Hands: {hands}")
        if bbv is not None:
            print(f"BB value: {fmt_money(bbv, currency)}")
        if bb100 is not None:
            print(f"bb/100: {fmt_float(bb100, 2)}")

    if fmt in ("mtt", "spin"):
        buyin = _to_float(session.get("buyin_total"))
        prize = _to_float(session.get("prize_total"))
        roi = _to_float(session.get("roi"))
        if buyin is not None and prize is not None:
            print(f"Buy-in total: {fmt_money(buyin, currency)}")
            print(f"Prize total:  {fmt_money(prize, currency)}")
        if roi is not None:
            print(f"ROI: {fmt_float(roi, 2, '%')}")

    note = (session.get("note") or "").strip()
    if note:
        print(f"Note: {note}")


def cmd_stats(args: argparse.Namespace) -> int:
    rows = read_rows(args.file)
    if not rows:
        print("Нет данных. Добавьте сессии через start/end или log.")
        return 0

    # Filters
    from_d = None
    to_d = None
    if args.from_date:
        try:
            from_d = parse_date_yyyy_mm_dd(args.from_date)
        except Exception:
            _print_err("Неверный формат --from. Используйте YYYY-MM-DD.")
            return 2
    if args.to_date:
        try:
            to_d = parse_date_yyyy_mm_dd(args.to_date)
        except Exception:
            _print_err("Неверный формат --to. Используйте YYYY-MM-DD.")
            return 2

    fmt_filter = args.format.lower() if args.format else None
    if fmt_filter and fmt_filter not in FORMATS:
        _print_err(f"--format должен быть одним из: {', '.join(FORMATS)}")
        return 2

    filt = []
    for r in rows:
        if fmt_filter and (r.get("format", "").lower() != fmt_filter):
            continue
        st = r.get("start_ts", "")
        try:
            d = dt_from_iso(st).date()
        except Exception:
            # if can't parse, keep it (or drop). We'll drop as corrupted.
            continue
        if from_d and d < from_d:
            continue
        if to_d and d > to_d:
            continue
        filt.append(r)

    if not filt:
        print("По выбранным фильтрам нет данных.")
        return 0

    # Aggregate
    total_sessions = len(filt)
    total_profit = 0.0
    total_minutes = 0

    # per format aggregates
    ag = {f: {"sessions": 0, "profit": 0.0, "minutes": 0, "hands": 0, "bb_profit": 0.0, "buyin": 0.0, "prize": 0.0} for f in FORMATS}

    for r in filt:
        fmt = (r.get("format") or "").lower()
        profit = _to_float(r.get("profit")) or 0.0
        dur = _to_int(r.get("duration_min")) or 0

        total_profit += profit
        total_minutes += dur

        if fmt in ag:
            ag[fmt]["sessions"] += 1
            ag[fmt]["profit"] += profit
            ag[fmt]["minutes"] += dur

        if fmt == "cash":
            hands = _to_int(r.get("hands")) or 0
            bb_profit = _to_float(r.get("bb_profit")) or 0.0
            ag["cash"]["hands"] += hands
            ag["cash"]["bb_profit"] += bb_profit

        if fmt in ("mtt", "spin"):
            buyin = _to_float(r.get("buyin_total")) or 0.0
            prize = _to_float(r.get("prize_total")) or 0.0
            ag[fmt]["buyin"] += buyin
            ag[fmt]["prize"] += prize

    total_hours = total_minutes / 60.0 if total_minutes else 0.0
    pph = total_profit / total_hours if total_hours > 0 else None

    print("=== PokerOK Session Tracker: STATS ===")
    if args.from_date or args.to_date or fmt_filter:
        parts = []
        if args.from_date:
            parts.append(f"from {args.from_date}")
        if args.to_date:
            parts.append(f"to {args.to_date}")
        if fmt_filter:
            parts.append(f"format={fmt_filter}")
        print("Фильтр:", ", ".join(parts))

    print(f"\nTotal sessions: {total_sessions}")
    print(f"Total profit:  {total_profit:.2f}")
    print(f"Total time:    {fmt_duration(total_minutes)}")
    print(f"Avg session:   {fmt_duration(int(round(total_minutes / total_sessions)))}")
    print(f"Profit/hour:   {fmt_float(pph, 2)}")

    print("\n--- Breakdown by format ---")
    for f in FORMATS:
        s = ag[f]["sessions"]
        if s == 0:
            continue
        minutes = ag[f]["minutes"]
        hours = minutes / 60.0 if minutes else 0.0
        prof = ag[f]["profit"]
        pph_f = prof / hours if hours > 0 else None
        print(f"\n{f.upper()}:")
        print(f"  sessions: {s}")
        print(f"  profit:   {prof:.2f}")
        print(f"  time:     {fmt_duration(minutes)}")
        print(f"  p/h:      {fmt_float(pph_f, 2)}")

        if f == "cash":
            hands = ag["cash"]["hands"]
            bb_profit = ag["cash"]["bb_profit"]
            # overall bb/100 from aggregated bb_profit and hands
            bb100 = (bb_profit / hands) * 100.0 if hands > 0 else None
            if hands > 0:
                print(f"  hands:    {hands}")
            if bb100 is not None:
                print(f"  bb/100:   {fmt_float(bb100, 2)}")
            else:
                print("  bb/100:   - (нужно указать hands и bb_value в сессиях)")

        if f in ("mtt", "spin"):
            buyin = ag[f]["buyin"]
            prize = ag[f]["prize"]
            profit_from_totals = prize - buyin
            roi = (profit_from_totals / buyin) * 100.0 if buyin > 0 else None
            if buyin > 0 or prize > 0:
                print(f"  buyin:    {buyin:.2f}")
                print(f"  prize:    {prize:.2f}")
            if roi is not None:
                print(f"  ROI:      {fmt_float(roi, 2, '%')}")
            else:
                print("  ROI:      - (нужно указать buyin_total и prize_total)")

    return 0


# ---------------------------
# Argparse
# ---------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tracker.py",
        description="PokerOK Session Tracker (one-file CLI).",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("--file", default=DEFAULT_CSV, help="Path to sessions CSV (default: sessions.csv)")
    p.add_argument("--active", default=DEFAULT_ACTIVE, help="Path to active session JSON (default: active_session.json)")

    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("start", help="Start a session (creates active_session.json)")
    sub.add_parser("end", help="End active session and save to CSV")
    sub.add_parser("log", help="Log a completed session in one command (no active session)")
    sub.add_parser("status", help="Show active session status")
    stats = sub.add_parser("stats", help="Show aggregated stats")
    stats.add_argument("--from", dest="from_date", help="Filter start date YYYY-MM-DD")
    stats.add_argument("--to", dest="to_date", help="Filter end date YYYY-MM-DD")
    stats.add_argument("--format", help="Filter by format: cash|mtt|spin")

    return p


def main(argv: List[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.cmd:
        parser.print_help()
        return 0

    if args.cmd == "start":
        return cmd_start(args)
    if args.cmd == "end":
        return cmd_end(args)
    if args.cmd == "log":
        return cmd_log(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "stats":
        return cmd_stats(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))