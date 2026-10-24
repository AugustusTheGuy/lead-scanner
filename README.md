# lead-scanner

A read-only, zero-dependency Python CLI that pulls freelance and contract leads from public job sources, scores them by estimated $/hour and fit, and writes a ranked Markdown + JSON report.

One module per source in `scan/sources/`; shared fetching, pay parsing, scoring and seen-state live in `scan/core.py`.

## Sources

`reddit` (r/forhire and related subs via the Arctic Shift archive API and Reddit Atom feeds), `craigslist`, `hn` (Hacker News hiring threads via the Algolia API), `freelancer`, `superteam`, `mercor`, `braintrust`, `arc`, `remoteboards` (RemoteOK, We Work Remotely), `linkedin` (public guest job search), `expensify`, `algora` (GitHub bounty search), and `x` (reads a local inbox JSON you populate yourself; the scanner never calls the X API).

## What it does

- **Fetch** with retries and backoff on 403/429/422, gzip handling, and rejection of HTML block pages served where JSON was expected.
- **Parse pay** from free text: fixed, hourly, monthly, salary ranges, bounties (`parse_pay`).
- **Score** each lead: `rank = $/h estimate x p(win) x (1 + fit/10)`. `p(win)` starts from stack fit and is adjusted for freshness and competition (comments/bids), with multipliers for flags such as `off-stack`, `scam-risk` (e.g. "upfront fee" language), `middleman`, `gated`, `salary`, `contest`.
- **Seen-state** marks leads NEW vs SEEN without hiding them; atomic writes, 30-day prune.
- **Report** to `scan/out/latest.json` and `scan/out/leads-<timestamp>.md`, plus per-source stats lines (`{source, http, n_raw, n_fit, ms}`).

## Requirements

Python 3.9+ (standard library only).

## Usage

```bash
python3 -m scan --all --top 20
python3 -m scan --source reddit,hn,remoteboards --hours 24 --new-only
python3 -m scan --source linkedin --json --no-save
```

Optional environment variables:

| Variable | Purpose |
|---|---|
| `GITHUB_TOKEN` / `GH_TOKEN` | Higher rate limit for the GitHub bounty search (read-only). |
| `ALGORA_SNIPER` | Path to an external bounty script that prints `{"candidates": [...]}` JSON. Optional. |
| `LEAD_SCANNER_BLOCKLIST` | Comma-separated usernames to flag as `scam-risk`. |
| `LEAD_SCANNER_SPAM_REPOS` | Comma-separated `owner/repo` names to skip in bounty search. |
| `LEAD_SCANNER_LEGACY_DIR` | Folder holding old `leads_seen.txt` / `hn_seen.txt` lists to import once. |

## Tests

```bash
python3 -m unittest scan.tests.test_scan -v              # offline
SCAN_LIVE=1 python3 -m unittest scan.tests.test_scan -v  # adds live network checks
```

The offline suite covers pay parsing, scoring and flagging, block-page rejection, retry-on-429 (against a local HTTP server), atomic seen-state, the Reddit/Craigslist classifiers, and the X inbox filter. Parser tests for individual sites need captured pages in `scan/tests/fixtures/`; those captures are third-party content and are not included in this repo, so those tests skip until you add your own.

## Notes

The scanner only reads public pages and APIs. It never posts, applies, or messages anyone. Respect each site's terms and rate limits.

## License

MIT
