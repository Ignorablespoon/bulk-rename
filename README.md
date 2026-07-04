# Bulk Rename & Folder Creator

A single-file Python CLI for bulk-renaming files and folders (search-and-replace or sequential numbering) and for bulk-creating new folders with a chosen naming scheme. No dependencies beyond the Python standard library.

Includes a built-in interactive shell with Cisco-IOS-style contextual help: press `?` at any point to see what you can type next, without needing to hit Enter first.

## Features

- **Rename** files and/or folders via:
  - Plain text or regex search-and-replace
  - Sequential numbering patterns (`file_{n:03d}{ext}`)
- **Create folders** in bulk using:
  - Default OS-style naming (`New Folder`, `New Folder (1)`, ...)
  - Plain numbering (`001`, `002`, ...)
  - Name + numbering (`file 1`, `file 2`, ...)
  - An explicit list of names you supply
- **Dry-run mode** to preview every change before it happens
- **Collision detection** — refuses to run if two items would end up with the same name, or if a target name already exists
- **Undo** — automatically logs the last batch so you can revert it
- **Interactive shell** with live `?` help, no dependencies required
- Filtering by extension, glob include/exclude patterns, and recursive folder scanning

## Requirements

- Python 3.8+
- No third-party packages required

## Installation

Clone the repo (or just download `bulk_rename.py`) and run it directly:

```bash
git clone https://github.com/Ignorablespoon/bulk-rename.git
cd bulk-rename
python3 bulk_rename.py --help
```

Optional for Linux: make it executable and drop it on your `PATH`:

```bash
chmod +x bulk_rename.py
sudo mv bulk_rename.py /usr/local/bin/bulk-rename
bulk-rename --help
```

## Quick Start

```bash
# Preview renaming all .jpg files: IMG_ -> vacation_
python3 bulk_rename.py rename ./photos --find "IMG_" --replace "vacation_" --ext jpg --dry-run

# Actually apply it
python3 bulk_rename.py rename ./photos --find "IMG_" --replace "vacation_" --ext jpg --yes

# Sequentially number files: file_001.jpg, file_002.jpg, ...
python3 bulk_rename.py rename ./photos --sequence "file_{n:03d}{ext}" --yes

# Create 5 new folders named Batch_01 .. Batch_05
python3 bulk_rename.py create-folders ./workspace --count 5 --style name-number --base-name "Batch" --padding 2

# Undo the last batch run in a folder
python3 bulk_rename.py undo ./photos
```

## Commands

### `rename`

Rename files and/or folders in a target directory.

```bash
python3 bulk_rename.py rename FOLDER [options]
```

**Choose one rename mode:**

| Flag | Description |
|---|---|
| `--find TEXT` | Text (or regex, with `--regex`) to search for |
| `--replace TEXT` | Replacement text (default: empty string) |
| `--regex` | Treat `--find` as a regular expression |
| `--sequence PATTERN` | Sequential numbering pattern, e.g. `"photo_{n:03d}{ext}"` |
| `--start N` | Starting number for `--sequence` (default: `1`) |
| `--step N` | Increment for `--sequence` (default: `1`) |

Sequence pattern placeholders: `{n}` = counter, `{name}` = original filename stem, `{ext}` = original extension (including the dot).

**Scope / filtering:**

| Flag | Description |
|---|---|
| `--target {files,folders,both}` | What to rename (default: `files`) |
| `-r`, `--recursive` | Recurse into subfolders |
| `--ext jpg,png` | Only include these extensions (files only) |
| `--include GLOB` | Only include names matching this glob |
| `--exclude GLOB` | Exclude names matching this glob |
| `--stem-only` | Apply `--find`/`--replace` to the filename stem only, leaving the extension untouched |
| `-i`, `--case-insensitive` | Case-insensitive matching for `--find` |
| `--sort-by {name,created,modified}` | Order used to assign sequence numbers (default: `name`) |

**Behavior:**

| Flag | Description |
|---|---|
| `--dry-run` | Preview planned renames without changing anything |
| `-y`, `--yes` | Skip the confirmation prompt |

### `create-folders`

Create new folders in a target directory using a chosen naming style.

```bash
python3 bulk_rename.py create-folders FOLDER [options]
```

| Flag | Description |
|---|---|
| `--style {default,number,name-number,list}` | Naming scheme (see table below) |
| `--count N` | How many folders to create (not needed for `--style list`) |
| `--base-name TEXT` | Base name for `default` and `name-number` styles |
| `--start N` | Starting number (default: `1`) |
| `--step N` | Increment between numbers (default: `1`) |
| `--padding N` | Zero-pad numbers to N digits (e.g. `3` → `001`) |
| `--names "A,B,C"` | Comma-separated folder names (for `--style list`) |
| `--names-file PATH` | Text file with one folder name per line (for `--style list`) |
| `--dry-run` | Preview planned folders without creating them |
| `-y`, `--yes` | Skip the confirmation prompt |

**Naming styles:**

| Style | Example output |
|---|---|
| `default` | `New Folder`, `New Folder (1)`, `New Folder (2)`, ... |
| `number` | `1`, `2`, `3`, ... (or `001`, `002`... with `--padding`) |
| `name-number` | `file 1`, `file 2`, `file 3`, ... |
| `list` | Exactly the names you supply |

### `undo`

Revert the most recent `rename` or `create-folders` batch run in a folder.

```bash
python3 bulk_rename.py undo FOLDER
```

- For renames: restores every file/folder to its previous name.
- For folder creation: removes the folders it created — but only if they're still empty, to avoid deleting anything unexpected.

Only the **last** batch is undoable; each run overwrites the log for that folder.

## Interactive Shell

Run the script with no arguments to enter an interactive shell:

```bash
python3 bulk_rename.py
```

```
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

bulk-rename>
```

From here you can:

- Press **`?`** at any point — even mid-word, without pressing Enter — to instantly see the available options for the command you're typing. The prompt then reappears with what you'd already typed so you can keep going.
- Type `?` or `help` on an empty prompt to list all commands.
- Type a full command (e.g. `rename ./photos --sequence "photo_{n:03d}{ext}" --dry-run`) and press Enter to run it.
- Type `clear` to clear the screen.
- Type `exit` or `quit` to leave.

> **Note:** Live `?` detection requires a real terminal. If the shell is run without one attached (e.g. piped input in a script or CI), it automatically falls back to standard line input — type the full line, then press Enter, to see the same behavior.

## How Undo Works

Every `rename` or `create-folders` run writes a small log file, `.bulk_rename_log.json`, into the target folder. Running `undo` on that folder reads the log, reverses the operation, and deletes the log file when the revert succeeds fully. If some items can't be restored (already moved, target now exists, folder no longer empty), those are reported and left alone.

## Examples

```bash
# Regex: strip a leading number and underscore, e.g. "01_report.pdf" -> "report.pdf"
python3 bulk_rename.py rename ./docs --find "^\d+_" --replace "" --regex --yes

# Rename subfolders instead of files
python3 bulk_rename.py rename ./projects --target folders --find "old" --replace "new" --yes

# Recursive, only .png/.jpg files, case-insensitive match
python3 bulk_rename.py rename ./assets -r --ext png,jpg --find "old" --replace "new" -i --yes

# Create folders from an explicit list stored in a file
python3 bulk_rename.py create-folders ./clients --style list --names-file client_names.txt
```

## Safety Notes

- Always available: run with `--dry-run` first to preview any rename or folder-creation batch before committing to it.
- The tool refuses to proceed if a rename plan would cause two items to collide, or overwrite something outside the batch.
- Renames are staged through temporary names internally so that swapping/cycling names (e.g. A→B, B→A) doesn't clobber anything mid-batch.

