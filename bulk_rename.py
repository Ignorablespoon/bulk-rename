#!/usr/bin/env python3
"""
bulk_rename.py — Bulk file/folder renamer & folder creator CLI

Three subcommands:

  rename          Rename files and/or folders via search-and-replace or
                  sequential numbering.
  create-folders  Create new folders using a default, numbered, name+number,
                  or explicit-list naming scheme.
  undo            Revert the last batch performed by either subcommand.

Examples
--------
Rename:
  # Preview replacing "IMG_" with "vacation_" in all .jpg files
  python bulk_rename.py rename ./photos --find "IMG_" --replace "vacation_" --ext jpg --dry-run

  # Sequential numbering: photo_001.jpg, photo_002.jpg, ...
  python bulk_rename.py rename ./photos --sequence "photo_{n:03d}{ext}" --yes

  # Rename subfolders instead of files
  python bulk_rename.py rename ./projects --target folders --find "old" --replace "new" --yes

Create folders:
  # Default OS-style naming: "New Folder", "New Folder (1)", "New Folder (2)"...
  python bulk_rename.py create-folders ./workspace --count 5 --style default

  # Plain numbering: 001, 002, 003 ...
  python bulk_rename.py create-folders ./workspace --count 10 --style number --padding 3

  # Name + numbering: "file 1", "file 2", "file 3" ...
  python bulk_rename.py create-folders ./workspace --count 3 --style name-number --base-name "file"

  # Explicit list of names
  python bulk_rename.py create-folders ./workspace --style list --names "Alpha,Beta,Gamma"
  python bulk_rename.py create-folders ./workspace --style list --names-file names.txt

Undo:
  python bulk_rename.py undo ./photos
"""

import argparse
import fnmatch
import json
import os
import re
import shlex
import sys
from datetime import datetime
from pathlib import Path

LOG_FILENAME = ".bulk_rename_log.json"


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

COMMAND_HELP = {
    "rename": "Rename files and/or folders (search-and-replace or sequential numbering)",
    "create-folders": "Create new folders (default, number, name-number, or list naming)",
    "undo": "Revert the last rename/create-folders batch",
}


def build_parser(require_command=True):
    """Build the argparse parser. Shared by CLI mode and the interactive shell."""
    p = argparse.ArgumentParser(
        prog="bulk_rename.py",
        description="Bulk-rename files/folders or bulk-create new folders.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="command", required=require_command)
    subparsers_map = {}

    # --- rename ---
    r = sub.add_parser("rename", help=COMMAND_HELP["rename"])
    subparsers_map["rename"] = r
    r.add_argument("folder", type=str, help="Folder containing items to rename")

    mode = r.add_argument_group("rename mode (choose one)")
    mode.add_argument("--find", type=str, help="Text or regex pattern to search for")
    mode.add_argument("--replace", type=str, default="", help="Replacement text")
    mode.add_argument("--regex", action="store_true", help="Treat --find as a regex")
    mode.add_argument(
        "--sequence",
        type=str,
        help=(
            "Sequential numbering pattern, e.g. 'photo_{n:03d}{ext}'. "
            "Placeholders: {n}=counter, {name}=original stem, {ext}=original extension (with dot)"
        ),
    )
    mode.add_argument("--start", type=int, default=1, help="Starting number for --sequence (default: 1)")
    mode.add_argument("--step", type=int, default=1, help="Increment for --sequence (default: 1)")

    scope = r.add_argument_group("scope / filtering")
    scope.add_argument(
        "--target",
        choices=["files", "folders", "both"],
        default="files",
        help="Rename files, subfolders, or both (default: files)",
    )
    scope.add_argument("-r", "--recursive", action="store_true", help="Recurse into subfolders")
    scope.add_argument("--ext", type=str, help="Comma-separated extensions to include, e.g. jpg,png (files only)")
    scope.add_argument("--include", type=str, help="Glob pattern names must match, e.g. 'IMG_*'")
    scope.add_argument("--exclude", type=str, help="Glob pattern to exclude")
    scope.add_argument("--stem-only", action="store_true", help="Apply --find/--replace to name stem only (skip extension)")
    scope.add_argument("-i", "--case-insensitive", action="store_true", help="Case-insensitive matching for --find")
    scope.add_argument(
        "--sort-by",
        choices=["name", "created", "modified"],
        default="name",
        help="Order used to assign sequence numbers (default: name)",
    )

    behavior = r.add_argument_group("behavior")
    behavior.add_argument("--dry-run", action="store_true", help="Show planned renames without applying them")
    behavior.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    # --- create-folders ---
    c = sub.add_parser("create-folders", help=COMMAND_HELP["create-folders"])
    subparsers_map["create-folders"] = c
    c.add_argument("folder", type=str, help="Parent folder to create new folders in")
    c.add_argument(
        "--style",
        choices=["default", "number", "name-number", "list"],
        default="default",
        help=(
            "default: 'New Folder', 'New Folder (1)', ... | "
            "number: '1', '2', ... | "
            "name-number: '<base-name> 1', '<base-name> 2', ... | "
            "list: use --names / --names-file exactly"
        ),
    )
    c.add_argument("--count", type=int, help="How many folders to create (not needed for --style list)")
    c.add_argument("--base-name", type=str, default=None, help="Base name for 'default' and 'name-number' styles")
    c.add_argument("--start", type=int, default=1, help="Starting number (default: 1)")
    c.add_argument("--step", type=int, default=1, help="Increment between numbers (default: 1)")
    c.add_argument("--padding", type=int, default=0, help="Zero-pad numbers to this many digits (e.g. 3 -> 001)")
    c.add_argument("--names", type=str, help="Comma-separated folder names (for --style list)")
    c.add_argument("--names-file", type=str, help="Path to a text file with one folder name per line (for --style list)")
    c.add_argument("--dry-run", action="store_true", help="Show planned folders without creating them")
    c.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    # --- undo ---
    u = sub.add_parser("undo", help=COMMAND_HELP["undo"])
    subparsers_map["undo"] = u
    u.add_argument("folder", type=str, help="Folder the last batch was run in")

    return p, subparsers_map


def parse_args():
    parser, _ = build_parser()
    return parser.parse_args()


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def gather_items(folder: Path, recursive: bool, target: str, ext_filter, include, exclude):
    pattern = "**/*" if recursive else "*"
    items = [f for f in folder.glob(pattern) if f.name != LOG_FILENAME]

    if target == "files":
        items = [f for f in items if f.is_file()]
    elif target == "folders":
        items = [f for f in items if f.is_dir()]
    else:  # both
        items = [f for f in items if f.is_file() or f.is_dir()]

    if ext_filter:
        allowed = {e.lower().lstrip(".") for e in ext_filter.split(",")}
        items = [f for f in items if f.is_dir() or f.suffix.lower().lstrip(".") in allowed]

    if include:
        items = [f for f in items if fnmatch.fnmatch(f.name, include)]

    if exclude:
        items = [f for f in items if not fnmatch.fnmatch(f.name, exclude)]

    return items


def sort_items(items, sort_by):
    if sort_by == "created":
        return sorted(items, key=lambda f: f.stat().st_ctime)
    if sort_by == "modified":
        return sorted(items, key=lambda f: f.stat().st_mtime)
    return sorted(items, key=lambda f: f.name.lower())


def plan_find_replace(items, find, replace, use_regex, case_insensitive, stem_only):
    plans = []
    flags = re.IGNORECASE if case_insensitive else 0
    for f in items:
        is_dir = f.is_dir()
        target = f.stem if (stem_only and not is_dir) else f.name
        if use_regex:
            new_target = re.sub(find, replace, target, flags=flags)
        elif case_insensitive:
            new_target = re.sub(re.escape(find), replace, target, flags=re.IGNORECASE)
        else:
            new_target = target.replace(find, replace)

        if stem_only and not is_dir:
            new_name = f"{new_target}{f.suffix}"
        else:
            new_name = new_target

        if new_name != f.name:
            plans.append((f, f.with_name(new_name)))
    return plans


def plan_sequence(items, pattern, start, step):
    plans = []
    n = start
    for f in items:
        new_name = pattern.format(n=n, name=f.stem, ext=f.suffix)
        plans.append((f, f.with_name(new_name)))
        n += step
    return plans


def check_collisions(plans):
    dest_names = [dst.name for _, dst in plans]
    seen = set()
    dupes = set()
    for name in dest_names:
        if name in seen:
            dupes.add(name)
        seen.add(name)

    problems = []
    if dupes:
        problems.append(f"Multiple items would be renamed to the same name: {', '.join(sorted(dupes))}")

    src_names = {src.name for src, _ in plans}
    for _, dst in plans:
        if dst.exists() and dst.name not in src_names:
            problems.append(f"Target already exists and is not part of this batch: {dst.name}")

    return problems


def preview_renames(plans, folder):
    print(f"\nPlanned renames in {folder} ({len(plans)} item(s)):\n")
    for src, dst in plans:
        rel_src = src.relative_to(folder)
        rel_dst = dst.relative_to(folder)
        marker = "  " if str(rel_src) == str(rel_dst) else "->"
        print(f"  {rel_src}  {marker}  {rel_dst}")
    print()


def write_log(folder: Path, action: str, **payload):
    log_path = folder / LOG_FILENAME
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        **payload,
    }
    log_path.write_text(json.dumps(entry, indent=2))
    return log_path


def confirm(prompt: str, auto_yes: bool) -> bool:
    if auto_yes:
        return True
    answer = input(prompt).strip().lower()
    return answer in ("y", "yes")


# --------------------------------------------------------------------------
# rename subcommand
# --------------------------------------------------------------------------

def run_rename(args):
    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        print(f"Error: '{folder}' is not a valid folder.", file=sys.stderr)
        sys.exit(1)

    if not args.find and not args.sequence:
        print("Error: specify either --find/--replace or --sequence.", file=sys.stderr)
        sys.exit(1)
    if args.find and args.sequence:
        print("Error: choose either --find/--replace or --sequence, not both.", file=sys.stderr)
        sys.exit(1)

    items = gather_items(folder, args.recursive, args.target, args.ext, args.include, args.exclude)
    if not items:
        print("No matching items found.")
        return
    items = sort_items(items, args.sort_by)

    if args.find:
        plans = plan_find_replace(items, args.find, args.replace, args.regex, args.case_insensitive, args.stem_only)
    else:
        plans = plan_sequence(items, args.sequence, args.start, args.step)

    if not plans:
        print("No items need renaming (no changes would result).")
        return

    problems = check_collisions(plans)
    if problems:
        print("Error: cannot proceed due to naming conflicts:", file=sys.stderr)
        for prob in problems:
            print(f"  - {prob}", file=sys.stderr)
        sys.exit(1)

    preview_renames(plans, folder)

    if args.dry_run:
        print("Dry run only — nothing was changed.")
        return

    if not confirm(f"Proceed with renaming {len(plans)} item(s)? [y/N] ", args.yes):
        print("Aborted. No items were changed.")
        return

    # Rename via temp names first to avoid clobbering when swapping/cycling names
    temp_plans = []
    for src, dst in plans:
        tmp = src.with_name(f".__tmp__{src.name}")
        src.rename(tmp)
        temp_plans.append((tmp, dst))
    for tmp, dst in temp_plans:
        tmp.rename(dst)

    log_path = write_log(
        folder, "rename",
        renames=[{"from": str(src), "to": str(dst)} for src, dst in plans],
    )
    print(f"Done. Renamed {len(plans)} item(s). Log saved to {log_path.name} (use 'undo' to revert).")


# --------------------------------------------------------------------------
# create-folders subcommand
# --------------------------------------------------------------------------

def load_names_list(args):
    if args.names_file:
        path = Path(args.names_file).expanduser().resolve()
        if not path.is_file():
            print(f"Error: names file '{path}' not found.", file=sys.stderr)
            sys.exit(1)
        names = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    elif args.names:
        names = [n.strip() for n in args.names.split(",") if n.strip()]
    else:
        print("Error: --style list requires --names or --names-file.", file=sys.stderr)
        sys.exit(1)

    if not names:
        print("Error: no folder names found in --names/--names-file.", file=sys.stderr)
        sys.exit(1)
    return names


def build_folder_names(args):
    if args.style == "list":
        return load_names_list(args)

    if not args.count or args.count < 1:
        print("Error: --count must be a positive integer for this style.", file=sys.stderr)
        sys.exit(1)

    names = []
    n = args.start
    for i in range(args.count):
        if args.style == "default":
            base = args.base_name or "New Folder"
            name = base if i == 0 else f"{base} ({i})"
        elif args.style == "number":
            name = str(n).zfill(args.padding) if args.padding else str(n)
        else:  # name-number
            base = args.base_name or "Folder"
            num = str(n).zfill(args.padding) if args.padding else str(n)
            name = f"{base} {num}"
        names.append(name)
        n += args.step
    return names


def run_create_folders(args):
    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        print(f"Error: '{folder}' is not a valid folder.", file=sys.stderr)
        sys.exit(1)

    names = build_folder_names(args)
    targets = [folder / name for name in names]

    # Collision checks
    seen = set()
    dupes = set()
    for t in targets:
        if t.name in seen:
            dupes.add(t.name)
        seen.add(t.name)
    problems = []
    if dupes:
        problems.append(f"Duplicate folder names in the plan: {', '.join(sorted(dupes))}")
    existing = [t.name for t in targets if t.exists()]
    if existing:
        problems.append(f"Already exists: {', '.join(existing)}")
    if problems:
        print("Error: cannot proceed due to conflicts:", file=sys.stderr)
        for prob in problems:
            print(f"  - {prob}", file=sys.stderr)
        sys.exit(1)

    print(f"\nPlanned new folders in {folder} ({len(targets)}):\n")
    for t in targets:
        print(f"  + {t.name}")
    print()

    if args.dry_run:
        print("Dry run only — nothing was created.")
        return

    if not confirm(f"Create {len(targets)} folder(s)? [y/N] ", args.yes):
        print("Aborted. No folders were created.")
        return

    created = []
    for t in targets:
        t.mkdir(parents=False, exist_ok=False)
        created.append(str(t))

    log_path = write_log(folder, "create-folders", created=created)
    print(f"Done. Created {len(created)} folder(s). Log saved to {log_path.name} (use 'undo' to revert).")


# --------------------------------------------------------------------------
# undo subcommand
# --------------------------------------------------------------------------

def run_undo(args):
    folder = Path(args.folder).expanduser().resolve()
    log_path = folder / LOG_FILENAME
    if not log_path.exists():
        print(f"No log found at {log_path}. Nothing to undo.")
        sys.exit(1)

    entry = json.loads(log_path.read_text())
    action = entry.get("action", "rename")
    timestamp = entry.get("timestamp", "unknown time")

    if action == "rename":
        renames = entry.get("renames", [])
        if not renames:
            print("Log is empty. Nothing to undo.")
            return
        print(f"\nReverting {len(renames)} rename(s) from {timestamp}:\n")
        failures = []
        for r in reversed(renames):
            src, dst = Path(r["to"]), Path(r["from"])
            print(f"  {src.name}  ->  {dst.name}")
            try:
                if not src.exists():
                    failures.append(f"Missing (already moved/renamed?): {src}")
                    continue
                if dst.exists():
                    failures.append(f"Cannot restore, target already exists: {dst}")
                    continue
                src.rename(dst)
            except OSError as e:
                failures.append(f"{src} -> {dst}: {e}")

        if failures:
            print("\nSome items could not be restored:")
            for f in failures:
                print(f"  - {f}")
        else:
            log_path.unlink()
            print("\nUndo complete. Log file removed.")

    elif action == "create-folders":
        created = entry.get("created", [])
        if not created:
            print("Log is empty. Nothing to undo.")
            return
        print(f"\nRemoving {len(created)} folder(s) created at {timestamp}:\n")
        failures = []
        for path_str in reversed(created):
            p = Path(path_str)
            print(f"  - {p.name}")
            try:
                if not p.exists():
                    failures.append(f"Missing (already removed/renamed?): {p}")
                    continue
                if any(p.iterdir()):
                    failures.append(f"Not empty, left in place: {p}")
                    continue
                p.rmdir()
            except OSError as e:
                failures.append(f"{p}: {e}")

        if failures:
            print("\nSome folders could not be removed:")
            for f in failures:
                print(f"  - {f}")
        else:
            log_path.unlink()
            print("\nUndo complete. Log file removed.")
    else:
        print(f"Unknown action '{action}' in log. Cannot undo automatically.")


def dispatch(args):
    if args.command == "rename":
        run_rename(args)
    elif args.command == "create-folders":
        run_create_folders(args)
    elif args.command == "undo":
        run_undo(args)


# --------------------------------------------------------------------------
# Interactive shell
# --------------------------------------------------------------------------

SHELL_BANNER = """
Bulk Rename & Folder Creator — interactive shell
=================================================
Commands:
  rename ...          Rename files/folders
  create-folders ...  Create new folders
  undo <folder>       Revert the last batch in a folder

Type '?' or 'help' to list commands.
Type '<command> ?'  (e.g. 'rename ?') to see that command's options — like
typing '?' after a Cisco IOS command to see what can come next.
Type 'clear' to clear the screen, 'exit' or 'quit' to leave.
"""


try:
    import termios
    import tty
    _HAS_TERMIOS = True
except ImportError:
    _HAS_TERMIOS = False

try:
    import msvcrt
    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False


def _read_char():
    """Read a single raw keystroke from stdin, blocking, no Enter required."""
    if _HAS_MSVCRT:
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):  # extended key (arrows, F-keys) - discard
            msvcrt.getwch()
            return ""
        return ch

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


def read_line_live(prompt, on_question_mark):
    """
    Read a line character-by-character so pressing '?' triggers help
    immediately (no Enter needed), then redraws the prompt with whatever
    had already been typed so the person can keep going — like typing
    '?' on a Cisco IOS device.
    """
    buffer = ""
    sys.stdout.write(prompt)
    sys.stdout.flush()

    while True:
        ch = _read_char()

        if ch == "":
            continue  # discarded escape/extended sequence

        if ch in ("\r", "\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
            return buffer

        if ch == "\x03":  # Ctrl+C
            sys.stdout.write("\n")
            raise KeyboardInterrupt

        if ch == "\x04" and not buffer:  # Ctrl+D on an empty line
            sys.stdout.write("\n")
            raise EOFError

        if ch in ("\x7f", "\x08"):  # Backspace
            if buffer:
                buffer = buffer[:-1]
                sys.stdout.write("\b \b")
                sys.stdout.flush()
            continue

        if ch == "\x1b":  # Escape sequence (arrow keys, etc.) - discard the rest
            _read_char()
            _read_char()
            continue

        if ch == "\t":
            continue

        if ch == "?":
            sys.stdout.write("?\n")
            sys.stdout.flush()
            on_question_mark(buffer)
            # Redraw the prompt with the command typed so far so they can continue
            sys.stdout.write(prompt + buffer)
            sys.stdout.flush()
            continue

        buffer += ch
        sys.stdout.write(ch)
        sys.stdout.flush()


def _can_read_live():
    return (_HAS_TERMIOS or _HAS_MSVCRT) and sys.stdin.isatty()


def print_shell_banner():
    print(SHELL_BANNER)


def print_top_level_help(subparsers_map):
    print("\nAvailable commands:\n")
    for name, help_text in COMMAND_HELP.items():
        print(f"  {name:<15} {help_text}")
    print("\nType '<command> ?' to see that command's full options, e.g.:")
    print("  rename ?")
    print("  create-folders ?\n")


def print_command_help(subparsers_map, name):
    subparser = subparsers_map.get(name)
    if subparser is None:
        print(f"\nUnknown command '{name}'.")
        print_top_level_help(subparsers_map)
        return
    print()
    subparser.print_help()
    print()


def run_shell():
    parser, subparsers_map = build_parser(require_command=False)
    print_shell_banner()

    def show_help_for(buffer_so_far):
        tokens = shlex.split(buffer_so_far) if buffer_so_far.strip() else []
        cmd_name = tokens[0] if tokens else None
        if cmd_name:
            print_command_help(subparsers_map, cmd_name)
        else:
            print_top_level_help(subparsers_map)

    live_mode = _can_read_live()

    while True:
        try:
            if live_mode:
                line = read_line_live("bulk-rename> ", show_help_for).strip()
            else:
                line = input("bulk-rename> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        if line in ("exit", "quit"):
            break

        if line in ("help", "?"):
            print_top_level_help(subparsers_map)
            continue

        if line == "clear":
            os.system("cls" if os.name == "nt" else "clear")
            continue

        try:
            tokens = shlex.split(line)
        except ValueError as e:
            print(f"Could not parse that line: {e}")
            continue

        if not tokens:
            continue

        # Cisco-style contextual help: "<command> ?" (with or without a space
        # before the '?') shows that command's options instead of running it.
        if tokens[-1] == "?" or tokens[-1].endswith("?"):
            if tokens[-1] != "?":
                tokens[-1] = tokens[-1][:-1]
            else:
                tokens = tokens[:-1]
            cmd_name = tokens[0] if tokens else None
            if cmd_name:
                print_command_help(subparsers_map, cmd_name)
            else:
                print_top_level_help(subparsers_map)
            continue

        if tokens[0] not in subparsers_map:
            print(f"Unknown command '{tokens[0]}'. Type '?' for a list of commands.")
            continue

        try:
            args = parser.parse_args(tokens)
        except SystemExit:
            # argparse already printed a usage/error message to stderr
            continue

        try:
            dispatch(args)
        except SystemExit:
            continue
        except Exception as e:
            print(f"Error: {e}")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main():
    if len(sys.argv) == 1:
        run_shell()
        return

    args = parse_args()
    dispatch(args)


if __name__ == "__main__":
    main()
