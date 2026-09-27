"""Read Excel files the app wrote earlier, so their data can be imported back.

Recognised by their sheets and column names, not by file name:
- the end-of-week report, history_exports/time_report_<Monday>.xlsx
  (week_report.build_week_report_xlsx): sheets "Weekly Table", "Entries"
  and, when there was something to put in them, "Reflection" and "Goals";
- the table download, timesheet_<Monday>.xlsx (service.week_table_xlsx, and
  "Download as Excel" in the Streamlit version): one sheet "Weekly Table".
The "By High Label" / "By Low Label" / "By Subject" sheets are totals of the
entries and are ignored.

Which week the data belongs to, in order of trust:
1. the dates in the Entries sheet (every entry carries its own date);
2. a YYYY-MM-DD date in the file name (both export names contain the Monday);
3. a week the caller supplies (the Import tab asks you) — used only when
   1 and 2 give nothing; otherwise WeekNeeded is raised.

Parsing only: no database access. service.import_excel applies the result.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from tracker.analytics import _DAY_ABBR, week_monday

# Column names as week_report.build_week_report_xlsx and service.week_table_xlsx write them.
ENTRY_COLUMNS = {"Date", "Subject", "Hours"}            # plus optional Low Label, High Label, Notes
TABLE_COLUMNS = {"Subject", *_DAY_ABBR}                 # plus optional Low Label, High Label, Total
TOTAL_ROW = "DAILY TOTAL"                               # the report's last Weekly Table row
REFLECTION_FIELDS = {"Strengths": "strengths", "Weaknesses": "weaknesses", "Plan for next week": "plan"}
OUTCOMES = {"not met": 0, "met": 1, "partial": 2}        # week_report._MET_LABELS, reversed
MAX_DAY_HOURS = 24.0
_NAME_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class ExcelImportError(ValueError):
    """The file can't be imported; the message says why."""


class WeekNeeded(ExcelImportError):
    """The file holds data but no date says which week it belongs to."""


@dataclass
class ImportedEntry:
    date: date
    name: str
    low: str
    high: str
    hours: float
    notes: str = ""


@dataclass
class ParsedWorkbook:
    filename: str
    kind: str                         # "report" | "table" | "entries"
    week: Optional[date]              # the Monday the Weekly Table, reflection and goals belong to
    week_source: str                  # "entries" | "file name" | "chosen"
    entries: list[ImportedEntry] = field(default_factory=list)
    reflection: Optional[dict] = None  # {"strengths", "weaknesses", "plan"}
    goals: list[dict] = field(default_factory=list)  # {"description", "target_hours", "subject", "met", "notes"}
    warnings: list[str] = field(default_factory=list)


def week_from_filename(filename: str) -> Optional[date]:
    m = _NAME_DATE.search(filename or "")
    if not m:
        return None
    try:
        return week_monday(date.fromisoformat(m.group(1)))
    except ValueError:
        return None


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def _raw(v) -> str:
    # Free text (notes, reflection) as written, not stripped: a stored text
    # ending in a space must compare equal to its own export, or a repeated
    # import would count it as changed.
    return "" if v is None else str(v)


def _number(v) -> Optional[float]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_date(v) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(_text(v)[:10])
    except ValueError:
        return None


def _sheets(data: bytes) -> dict[str, list[tuple]]:
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, OSError) as e:
        raise ExcelImportError("not an Excel .xlsx file") from e
    try:
        return {ws.title: [tuple(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
    finally:
        wb.close()


def _find_table(sheets: dict[str, list[tuple]], required: set[str], prefer: str):
    """(column index by name, data rows) of the first sheet whose header has all
    required columns; the sheet named `prefer` is tried first."""
    for title in sorted(sheets, key=lambda t: t != prefer):
        rows = sheets[title]
        if not rows:
            continue
        header = [_text(c) for c in rows[0]]
        if required <= set(header):
            return {name: i for i, name in enumerate(header) if name}, rows[1:]
    return None


def _cell(row: tuple, cols: dict, name: str):
    i = cols.get(name)
    return row[i] if i is not None and i < len(row) else None


def _hours_ok(h: Optional[float], where: str, warnings: list[str]) -> bool:
    if h is None or h == 0:
        return False
    if not 0 < h <= MAX_DAY_HOURS:
        warnings.append(f"{where}: {h:g} hours is not between 0 and 24; skipped")
        return False
    return True


def parse_workbook(data: bytes, filename: str, week: Optional[date] = None) -> ParsedWorkbook:
    """Read one file. `week` is used only when the file has no date of its own (see the module docstring)."""
    sheets = _sheets(data)
    name_week = week_from_filename(filename)
    warnings: list[str] = []
    entries: list[ImportedEntry] = []

    # 1. The Entries sheet: every row has its own date and note.
    entry_table = _find_table(sheets, ENTRY_COLUMNS, "Entries")
    if entry_table:
        cols, rows = entry_table
        for n, row in enumerate(rows, start=2):
            name = _text(_cell(row, cols, "Subject"))
            if not name:
                continue
            d = _to_date(_cell(row, cols, "Date"))
            if d is None:
                warnings.append(f"Entries row {n}: no readable date; skipped")
                continue
            h = _number(_cell(row, cols, "Hours"))
            if not _hours_ok(h, f"Entries row {n}", warnings):
                continue
            entries.append(ImportedEntry(d, name, _text(_cell(row, cols, "Low Label")),
                                         _text(_cell(row, cols, "High Label")), h, _raw(_cell(row, cols, "Notes"))))
    entry_weeks = sorted({week_monday(e.date) for e in entries})

    # The week for everything without its own date (table, reflection, goals).
    # A chosen week only fills a gap: it never overrides a date the file has,
    # so one --week for a whole folder can't move dated files.
    if name_week is not None:
        target, source = name_week, "file name"
    elif len(entry_weeks) == 1:
        target, source = entry_weeks[0], "entries"
    elif week is not None:
        target, source = week_monday(week), "chosen"
    else:
        target, source = None, ""
    if entry_weeks:
        source = "entries"
        if name_week and name_week not in entry_weeks:
            warnings.append(f"The name says the week of {name_week}, but the entries are dated "
                            f"{', '.join(str(w) for w in entry_weeks)}; each entry keeps its own date")

    # 2. The Weekly Table: only when there is no Entries sheet (a report has
    # both, with the same hours; the Entries sheet also has dates and notes).
    kind = "report" if "Entries" in sheets else "entries" if entry_table else "table"
    table = _find_table(sheets, TABLE_COLUMNS, "Weekly Table")
    table_rows = []
    if table and not entry_table:
        cols, rows = table
        table_rows = [r for r in rows if _text(_cell(r, cols, "Subject")) not in ("", TOTAL_ROW)]
        if table_rows and target is None:
            raise WeekNeeded("the file has no dates and no date in its name; choose its week")
        for row in table_rows:
            name = _text(_cell(row, cols, "Subject"))
            for i, day in enumerate(_DAY_ABBR):
                h = _number(_cell(row, cols, day))
                if _hours_ok(h, f"{name} on {day}", warnings):
                    entries.append(ImportedEntry(target + timedelta(days=i), name, _text(_cell(row, cols, "Low Label")),
                                                 _text(_cell(row, cols, "High Label")), h))

    # 3. Reflection and goals of the report's week.
    reflection = None
    refl = _find_table(sheets, {"Field", "Text"}, "Reflection")
    if refl:
        cols, rows = refl
        values = {REFLECTION_FIELDS[_text(_cell(r, cols, "Field"))]: _raw(_cell(r, cols, "Text"))
                  for r in rows if _text(_cell(r, cols, "Field")) in REFLECTION_FIELDS}
        if any(v.strip() for v in values.values()):
            reflection = {k: values.get(k, "") for k in REFLECTION_FIELDS.values()}
    goals = []
    gt = _find_table(sheets, {"Goal"}, "Goals")
    if gt:
        cols, rows = gt
        for r in rows:
            desc = _text(_cell(r, cols, "Goal"))
            if not desc:
                continue
            target_h = _number(_cell(r, cols, "Target hours"))
            goals.append({
                "description": desc,
                "target_hours": target_h if target_h and target_h > 0 else None,
                "subject": _text(_cell(r, cols, "Subject")),
                # "Not evaluated" (or anything else) means no outcome to import.
                "met": OUTCOMES.get(_text(_cell(r, cols, "Outcome")).casefold()),
                "notes": _raw(_cell(r, cols, "Evaluation notes")),
            })
    if (reflection or goals) and target is None:
        raise WeekNeeded("the file has a reflection or goals but no date in its name; choose its week")

    if not entries and not reflection and not goals:
        if entry_table or table_rows or table:
            warnings.append("the file has no hours, reflection or goals")
        else:
            raise ExcelImportError("no Time Tracker data found (expected a sheet with Subject and Mon…Sun "
                                   "columns, or with Date, Subject and Hours)")
    return ParsedWorkbook(filename, kind, target, source, entries, reflection, goals, warnings)
