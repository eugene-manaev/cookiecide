# Cookiecide

`cookiecide` is a small Safari cleanup tool for people who want selective control over website data instead of wiping everything.

It keeps two git-tracked files:

- `website_data.txt`: the current domains shown in Safari's `Manage Website Data…` list
- `blacklist.txt`: domains that should be removed from Safari automatically

When you run the script, it:

1. opens Safari's `Settings > Privacy > Manage Website Data…`
2. reads the current website-data list from the UI
3. removes anything already listed in `blacklist.txt`
4. prompts you about newly seen domains
5. adds newly rejected domains to the blacklist
6. updates the tracked files and commits the result

This is meant for people who want to keep normal sites like YouTube, work apps, and banking sites, while repeatedly deleting random trackers, chat widgets, coupon junk, and other low-value domains.

## Usage

```bash
./cookiecide.py
```

Useful flags:

- `--scan-only`: refresh `website_data.txt` without prompting or deleting
- `--dry-run`: show what would happen without removing or committing
- `--no-commit`: update files without creating a git commit

## Notes

- The script uses Safari UI automation through `osascript` and `System Events`.
- Your terminal app may need macOS Accessibility permission.
- Deletion is done through Safari's own Website Data dialog, not by deleting WebKit storage files directly.
