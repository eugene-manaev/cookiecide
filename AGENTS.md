# Cookiecide

This directory contains a Safari website-data triage workflow.

## Files

- `cookiecide.py`: CLI that inventories Safari website-data domains, removes blacklisted entries through Safari's own Website Data dialog, classifies newly seen domains with OpenAI, updates tracked files, and commits the result.
- `blacklist.txt`: one domain per line. Any domain in this file is treated as junk and removed from Safari on the next run.
- `website_data.txt`: sorted inventory of currently known Safari website-data domains after blacklist removals.

## Agent Flow

1. Work from the repository root.
2. Prefer updating `cookiecide.py`, `blacklist.txt`, and `website_data.txt` rather than adding duplicate scripts.
3. Keep `blacklist.txt` and `website_data.txt` sorted alphabetically, one domain per line.
4. Use Safari UI automation for deletion. Do not delete hashed WebKit storage directories directly.
5. The intended command is `./cookiecide.py` or `python3 cookiecide.py`.
6. The script may need macOS Accessibility permission for the terminal app because it drives Safari through `osascript` and `System Events`.
7. The script should:
   - collect the current domain inventory from Safari's `Manage Website Data…` UI list
   - remove any currently blacklisted entries from Safari
   - classify newly seen domains with OpenAI and use the result by default
   - fall back to a manual yes/no decision only if the OpenAI call fails
   - remove newly blacklisted entries from Safari
   - update `blacklist.txt` and `website_data.txt`
   - commit those two files if they changed
8. If an agent changes the workflow, update this file in the same commit.
