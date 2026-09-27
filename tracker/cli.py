"""The `time-tracker` command.

  time-tracker                 open the app in your browser (same as `gui`)
  time-tracker gui             the same, with --port / --no-browser
  time-tracker shortcut        put a Time Tracker shortcut with its icon on the desktop (Windows)
  time-tracker where           show where your data is kept
  time-tracker import-db FILE  use a copy of another timesheet.db (e.g. from an old install)
  time-tracker import-excel PATH...  add the data of Excel reports from earlier runs (files or folders)
  time-tracker --version

argparse, not click: the command is this small and the standard library
keeps the dependency list to what the app itself needs.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, paths


def _gui(args) -> None:
    from .web.launcher import main as launch

    launch(port=args.port, open_browser=not args.no_browser)


def _shortcut(_args) -> None:
    from .shortcut import create_desktop_shortcut, icon_path

    try:
        path = create_desktop_shortcut()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        print(f"To set the icon by hand: right-click a shortcut → Properties → Change Icon → {icon_path()}",
              file=sys.stderr)
        sys.exit(1)
    print(f"Created {path}. Double-click it to open Time Tracker.")


def _where(_args) -> None:
    db = paths.db_path()
    print(f"Data folder:    {paths.home()}")
    print(f"Database:       {db}{'' if db.exists() else '  (not created yet)'}")
    print(f"Excel reports:  {paths.export_dir()}")
    legacy = paths.legacy_db_path()
    if legacy.exists():
        print(f"Old database:   {legacy}  (copied to the data folder on first start if none was there)")


def _import_db(args) -> None:
    try:
        backup = paths.import_db(Path(args.file), force=args.force)
    except (ValueError, FileExistsError) as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    if backup:
        print(f"The previous database was saved as {backup}")
    print(f"Imported {args.file} into {paths.db_path()}. Restart the app if it is open.")


def _xlsx_files(targets: list[str]) -> list[Path]:
    """Files as given, folders expanded to their .xlsx files (Excel's ~$ lock files skipped)."""
    out = []
    for t in targets:
        p = Path(t).expanduser()
        if p.is_dir():
            out += sorted(f for f in p.glob("*.xlsx") if not f.name.startswith("~$"))
        elif p.is_file():
            out.append(p)
        else:
            print(f"Not found: {p}", file=sys.stderr)
            sys.exit(1)
    return out


def _import_excel(args) -> None:
    from . import service
    from .database import TimesheetDB

    files = _xlsx_files(args.paths)
    if not files:
        print("No .xlsx files found.", file=sys.stderr)
        sys.exit(1)
    data = [(f.name, f.read_bytes()) for f in files]
    weeks = {str(i): args.week for i in range(len(data))} if args.week else None
    mode = "replace" if args.replace else "keep"
    try:
        if args.dry_run:
            # Preview against what a real run would add to: the app's database,
            # or the old one that adopt_legacy_db would copy there first.
            db, legacy = paths.db_path(), paths.legacy_db_path()
            res = service.preview_import(db if db.exists() or not legacy.exists() else legacy, data, mode, weeks)
        else:
            paths.adopt_legacy_db()  # an old database must be in place before adding to it
            with TimesheetDB(str(paths.db_path())) as db:
                res = service.import_excel(db, data, mode, weeks)
    except service.UserError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    for f in res["files"]:
        if not f["ok"]:
            hint = " (give it one with --week YYYY-MM-DD)" if f["needs_week"] else ""
            print(f"✗ {f['name']}: {f['error']}{hint}")
            continue
        e = f["entries"]
        weeks_txt = ", ".join(f["weeks"]) or "no week"
        print(f"✓ {f['name']}: week {weeks_txt} · {f['hours']:g} h · days new {e['new']}, same {e['same']}, "
              f"different {e['different']}{' (replaced)' if mode == 'replace' and e['different'] else ''} · "
              f"reflection {f['reflection']} · goals new {f['goals']['new']}")
        for w in f["warnings"]:
            print(f"    note: {w}")
    for w in res["weeks"]:
        print(f"  week of {w['week_start']}: {w['hours_before']:g} h → {w['hours_after']:g} h")
    if args.dry_run:
        print("Dry run: nothing was changed.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="time-tracker", description="Personal time, progress and reflection tracker.")
    parser.add_argument("--version", action="version", version=f"time-tracker {__version__}")
    sub = parser.add_subparsers(dest="command")

    from .web.launcher import DEFAULT_PORT

    p = sub.add_parser("gui", help="open the app in your browser (the default)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port on 127.0.0.1 (default {DEFAULT_PORT}); another free one is used if taken")
    p.add_argument("--no-browser", action="store_true", help="don't open the browser")
    p.set_defaults(func=_gui)

    sub.add_parser("shortcut", help="put a shortcut with the app icon on the desktop (Windows)").set_defaults(func=_shortcut)
    sub.add_parser("where", help="show where your data is kept").set_defaults(func=_where)

    p = sub.add_parser("import-db", help="use a copy of another timesheet.db as your data")
    p.add_argument("file", help="path to a timesheet.db")
    p.add_argument("--force", action="store_true", help="replace an existing database (a backup copy is kept)")
    p.set_defaults(func=_import_db)

    p = sub.add_parser("import-excel", help="add the data of Excel files from earlier runs (reports or table downloads)")
    p.add_argument("paths", nargs="+", help=".xlsx files or folders of them (e.g. history_exports)")
    p.add_argument("--replace", action="store_true",
                   help="where a day already has different hours, use the file's (default: keep the app's)")
    p.add_argument("--week", help="YYYY-MM-DD: the week for files with no date inside or in their name (dated files keep theirs)")
    p.add_argument("--dry-run", action="store_true", help="only show what would change")
    p.set_defaults(func=_import_excel)

    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["gui", *(argv or [])])
    args.func(args)


if __name__ == "__main__":
    main()
