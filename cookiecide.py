#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
BLACKLIST_PATH = ROOT / "blacklist.txt"
INVENTORY_PATH = ROOT / "website_data.txt"
HELPER_DEBUG_LOG = ROOT / "openai-helper.log"
OPENAI_MODEL = "gpt-5.4-mini"

EXCLUDED_SUFFIXES = (
    ".local",
    ".arpa",
)


APPLE_SCRIPT = r"""
on waitForWebsiteDataReady()
  tell application "System Events"
    tell process "Safari"
      if not (exists sheet 1 of front window) then error "Safari Website Data sheet did not open."
      repeat 80 times
        tell sheet 1 of front window
          set isLoading to false
          try
            if exists static text "Loading Website Data..." then set isLoading to true
          end try
          try
            if exists static text "Loading Website Data…" then set isLoading to true
          end try
          if not isLoading then return "ready"
        end tell
        delay 0.25
      end repeat
      error "Safari Website Data sheet is still loading."
    end tell
  end tell
end waitForWebsiteDataReady

on openWebsiteDataSheet()
  tell application "Safari" to activate
  tell application "System Events"
    tell process "Safari"
      if not (exists front window) then error "Safari must have a front window."
      if exists sheet 1 of front window then return "already open"
      click menu item "Settings…" of menu "Safari" of menu bar item "Safari" of menu bar 1
      delay 0.8
      if not (exists front window) then error "Safari settings window did not open."
      try
        click radio button "Privacy" of toolbar 1 of front window
      on error
        try
          click button "Privacy" of toolbar 1 of front window
        end try
      end try
      delay 0.5
      try
        click button "Manage Website Data…" of group 1 of group 1 of front window
        delay 0.6
      on error
        error "Safari Privacy pane is open, but the Manage Website Data button could not be clicked automatically."
      end try
      if not (exists sheet 1 of front window) then error "Safari Website Data sheet did not open."
    end tell
  end tell
  return waitForWebsiteDataReady()
end openWebsiteDataSheet

on closeWebsiteDataSheet()
  tell application "System Events"
    tell process "Safari"
      if exists sheet 1 of front window then
        try
          click button "Done" of sheet 1 of front window
          delay 0.3
        end try
      end if
    end tell
  end tell
end closeWebsiteDataSheet

on removeDomain(targetDomain)
  waitForWebsiteDataReady()
  tell application "System Events"
    tell process "Safari"
      tell sheet 1 of front window
        set value of text field 1 to ""
        delay 0.08
        set value of text field 1 to targetDomain
        delay 0.45
        set rowCount to count of rows of table 1 of scroll area 1
        if rowCount is 0 then return "not found"
        select row 1 of table 1 of scroll area 1
        delay 0.12
        if not (enabled of button "Remove") then return "not removable"
        click button "Remove"
      end tell
      delay 0.3
      try
        if exists button "Remove Now" of sheet 1 of front window then
          click button "Remove Now" of sheet 1 of front window
          delay 0.2
        end if
      end try
      return "removed"
    end tell
  end tell
end removeDomain

on countMatches(targetDomain)
  waitForWebsiteDataReady()
  tell application "System Events"
    tell process "Safari"
      tell sheet 1 of front window
        set value of text field 1 to ""
        delay 0.08
        set value of text field 1 to targetDomain
        delay 0.35
        return count of rows of table 1 of scroll area 1
      end tell
    end tell
  end tell
end countMatches

on listWebsiteDataDomains()
  waitForWebsiteDataReady()
  tell application "System Events"
    tell process "Safari"
      tell sheet 1 of front window
        set value of text field 1 to ""
        delay 0.35
        set t to table 1 of scroll area 1
        set out to {}
        repeat with r in rows of t
          try
            set end of out to (value of static text 1 of UI element 1 of r as text)
          on error
            try
              set end of out to (name of r as text)
            end try
          end try
        end repeat
        return out
      end tell
    end tell
  end tell
end listWebsiteDataDomains
"""


@dataclass
class RemovalResult:
    domain: str
    status: str


@dataclass
class CodexDecision:
    decision: str
    reason: str


def run_applescript(body: str) -> str:
    script = APPLE_SCRIPT + "\n" + body
    proc = subprocess.run(
        ["osascript", "-"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(stderr or "AppleScript command failed")
    return proc.stdout.strip()


def normalize_domain(domain: str) -> str | None:
    domain = domain.strip().lower().strip(".")
    if not domain or domain == "localhost":
        return None
    if any(domain.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return None
    if domain.count(".") == 0:
        return None
    return domain


def sorted_unique(items: Iterable[str]) -> list[str]:
    return sorted({item for item in items if item})


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def write_lines(path: Path, lines: Iterable[str]) -> None:
    normalized = sorted_unique(lines)
    text = "\n".join(normalized)
    if normalized:
        text += "\n"
    path.write_text(text)


def append_helper_debug_log(domain: str, request_body: str, response_body: str, note: str) -> None:
    with HELPER_DEBUG_LOG.open("a") as fh:
        fh.write(f"domain: {domain}\n")
        fh.write(f"note: {note}\n")
        if request_body:
            fh.write("request:\n")
            fh.write(request_body.rstrip() + "\n")
        if response_body:
            fh.write("response:\n")
            fh.write(response_body.rstrip() + "\n")
        fh.write("---\n")


def ask_openai_about_domain(domain: str) -> CodexDecision:
    prompt = f"""
You are classifying a Safari website-data domain for a blacklist.

Domain: {domain}

Rule:
- Return "y" if this domain should be blacklisted and removed.
- Return "n" if this domain should be kept.
- Do not keep a domain just because it looks legitimate.
- Keep a domain only if it is both trustworthy and there is a clear, reasonable need for cookie or local storage usage.
- If the site looks legitimate but there is no obvious reason it needs browser storage, prefer "y".
- Blacklist obvious adtech, trackers, coupon junk, low-trust widgets, suspicious domains, and random marketing tech.

Reply as JSON only:
{{"decision":"y|n","reason":"short reason"}}
""".strip()

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    request_payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "response_format": {"type": "json_object"},
    }
    request_body = json.dumps(request_payload)

    print(f"Asking OpenAI about {domain} with {OPENAI_MODEL}...")
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=request_body.encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        append_helper_debug_log(domain, request_body, response_body, f"http-error={exc.code}")
        raise RuntimeError(
            f"OpenAI helper failed with HTTP {exc.code}. See {HELPER_DEBUG_LOG.name} for details."
        ) from exc
    except urllib.error.URLError as exc:
        append_helper_debug_log(domain, request_body, str(exc), "url-error")
        raise RuntimeError(
            f"OpenAI helper failed to connect. See {HELPER_DEBUG_LOG.name} for details."
        ) from exc
    except TimeoutError as exc:
        append_helper_debug_log(domain, request_body, "", "timeout")
        raise RuntimeError(
            f"OpenAI helper timed out after 30s. See {HELPER_DEBUG_LOG.name} for details."
        ) from exc

    append_helper_debug_log(domain, request_body, response_body, "ok")

    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"OpenAI helper returned invalid JSON. See {HELPER_DEBUG_LOG.name} for details."
        ) from exc

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"OpenAI helper returned no choices. See {HELPER_DEBUG_LOG.name} for details.")

    message = choices[0].get("message", {})
    last_text = str(message.get("content", "")).strip()

    if not last_text:
        raise RuntimeError(f"OpenAI helper returned no final message. See {HELPER_DEBUG_LOG.name} for details.")

    try:
        payload = json.loads(last_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"OpenAI helper returned invalid JSON content. See {HELPER_DEBUG_LOG.name} for details."
        ) from exc

    decision = str(payload.get("decision", "")).strip().lower()
    reason = str(payload.get("reason", "")).strip()
    if decision not in {"y", "n"}:
        raise RuntimeError(f"OpenAI helper returned invalid decision: {decision!r}")
    return CodexDecision(decision=decision, reason=reason)

def collect_inventory() -> list[str]:
    open_website_data_sheet()
    raw_output = run_applescript("return listWebsiteDataDomains()")
    domains = []
    for line in raw_output.split(","):
        normalized = normalize_domain(line)
        if normalized:
            domains.append(normalized)
    return sorted_unique(domains)


def ensure_repo_root() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    if not (ROOT / ".git").exists():
        subprocess.run(["git", "init"], cwd=ROOT, check=True)


def ensure_support_files() -> None:
    for path in (BLACKLIST_PATH, INVENTORY_PATH):
        if not path.exists():
            path.write_text("")


def open_website_data_sheet() -> None:
    run_applescript('return openWebsiteDataSheet()')


def close_website_data_sheet() -> None:
    try:
        run_applescript("closeWebsiteDataSheet()\nreturn \"closed\"")
    except RuntimeError:
        pass


def remove_domains(domains: Iterable[str], dry_run: bool) -> list[RemovalResult]:
    results: list[RemovalResult] = []
    for domain in domains:
        if dry_run:
            results.append(RemovalResult(domain, "dry-run"))
            continue
        status = run_applescript(f'return removeDomain("{domain}")')
        results.append(RemovalResult(domain, status))
    return results


def review_new_domains(domains: Iterable[str]) -> tuple[list[str], list[str]]:
    blacklist_additions: list[str] = []
    whitelist_additions: list[str] = []

    for domain in domains:
        try:
            decision = ask_openai_about_domain(domain)
        except RuntimeError as err:
            print(f"OpenAI helper failed for {domain}: {err}")
            while True:
                reply = input(f"Fallback decision for '{domain}' [y/N] ").strip().lower()
                if reply in ("", "n", "no"):
                    whitelist_additions.append(domain)
                    break
                if reply in ("y", "yes"):
                    blacklist_additions.append(domain)
                    break
                print("Please answer y or n.")
            continue

        print(f"OpenAI: {domain}: {decision.decision.upper()} - {decision.reason}")
        if decision.decision == "y":
            blacklist_additions.append(domain)
        else:
            whitelist_additions.append(domain)

    return blacklist_additions, whitelist_additions


def git_commit(paths: Iterable[Path], message: str, dry_run: bool) -> None:
    if dry_run:
        return

    rel_paths = [str(path.relative_to(ROOT)) for path in paths]
    subprocess.run(["git", "add", *rel_paths], cwd=ROOT, check=True)

    diff_proc = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
        check=False,
    )
    if diff_proc.returncode == 0:
        return

    subprocess.run(["git", "commit", "-m", message], cwd=ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Track Safari website data, blacklist junk domains, and remove them through Safari."
    )
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="Refresh website_data.txt from Safari's Website Data UI list without prompting, removing, or committing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not remove from Safari or commit, but still update local files to show the resulting state.",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Skip git commit after updating files.",
    )
    return parser.parse_args()


def print_removal_summary(results: Iterable[RemovalResult], heading: str) -> None:
    rows = list(results)
    if not rows:
        return
    print(heading)
    for row in rows:
        print(f"  {row.domain}: {row.status}")


def main() -> int:
    args = parse_args()

    ensure_repo_root()
    ensure_support_files()

    blacklist = set(read_lines(BLACKLIST_PATH))
    previous_inventory = set(read_lines(INVENTORY_PATH))

    current_inventory = set(collect_inventory())

    if args.scan_only:
        write_lines(INVENTORY_PATH, current_inventory)
        if not args.dry_run:
            close_website_data_sheet()
        print(f"Wrote {len(current_inventory)} domains to {INVENTORY_PATH}")
        return 0

    blacklisted_present = sorted(domain for domain in blacklist if domain in current_inventory)

    first_pass_results = remove_domains(blacklisted_present, dry_run=args.dry_run)
    print_removal_summary(first_pass_results, "Existing blacklist removals:")

    current_inventory = set(collect_inventory()) - set(blacklisted_present)
    known_domains = previous_inventory | blacklist
    new_domains = sorted(domain for domain in current_inventory if domain not in known_domains)

    if new_domains:
        print("New domains:")
        for domain in new_domains:
            print(f"  {domain}")
    else:
        print("No new domains to review.")

    blacklist_additions: list[str] = []
    if new_domains:
        blacklist_additions, _ = review_new_domains(new_domains)
        if blacklist_additions:
            blacklist.update(blacklist_additions)
            write_lines(BLACKLIST_PATH, blacklist)
            if not args.dry_run:
                open_website_data_sheet()

    second_pass_results = remove_domains(blacklist_additions, dry_run=args.dry_run)
    print_removal_summary(second_pass_results, "New blacklist removals:")

    final_inventory = current_inventory - set(blacklist_additions)
    write_lines(INVENTORY_PATH, final_inventory)
    write_lines(BLACKLIST_PATH, blacklist)

    if not args.dry_run:
        close_website_data_sheet()

    if not args.no_commit:
        git_commit(
            [BLACKLIST_PATH, INVENTORY_PATH],
            message="Update Safari website data inventory and blacklist",
            dry_run=args.dry_run,
        )

    print(f"Tracked domains: {len(final_inventory)}")
    print(f"Blacklisted domains: {len(blacklist)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
