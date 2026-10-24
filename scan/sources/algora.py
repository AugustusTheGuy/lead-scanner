"""Algora/GitHub bounties ($100+) via an optional external sniper script (ALGORA_SNIPER) (fixed: default --min 100, spam-repo
filter stars>=50 & age>=90d, deferred bounties no longer lost) + 3 extra GitHub searches."""
import json, os, re, subprocess, sys, time, urllib.parse
from ..core import get, Lead, log, FetchError, STATS

NAME = "algora"
SNIPER = os.environ.get("ALGORA_SNIPER", "")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
EXTRA = ['"algora-pbc" in:comments state:open is:issue',
         'label:"💎 Bounty" -repo:limitlessprojects/go-hybrid state:open is:issue',
         '"/bounty $" in:comments state:open is:issue']


SPAM_REPOS = {r.strip().lower() for r in os.environ.get("LEAD_SCANNER_SPAM_REPOS", "").split(",") if r.strip()}
_REPO = {}


def vetted(repo):
    """stars >= 50 and repo age >= 90 days (GitHub bounty search is flooded by same-day bot repos)."""
    if repo not in _REPO:
        try:
            d = get(f"https://api.github.com/repos/{repo}", expect="json", headers=gh_headers(), ua="delphi-lead-scan")
            from datetime import datetime
            age = time.time() - datetime.fromisoformat(d["created_at"].replace("Z", "+00:00")).timestamp()
            _REPO[repo] = d.get("stargazers_count", 0) >= 50 and age >= 90 * 86400
        except FetchError:
            _REPO[repo] = False
    return _REPO[repo]


def gh_headers():
    return {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})}


def scan(hours=72, live=True):
    t0 = time.time(); leads = []
    if not SNIPER or not os.path.exists(SNIPER):
        log(NAME, "info", "ALGORA_SNIPER not set; using GitHub search only")
        r = subprocess.CompletedProcess([], 0, stdout='{"candidates": []}', stderr="")
    else:
        r = subprocess.run([sys.executable, SNIPER, "--json", "--min", "100"], capture_output=True, text=True, timeout=240)
    if r.returncode == 2:
        log(NAME, "warn", "sniper rate-limited (exit 2): " + r.stdout[-200:])
    elif r.returncode != 0:
        log(NAME, "error", f"sniper exit {r.returncode}: {r.stderr[-300:]}")
    else:
        for c in json.loads(r.stdout)["candidates"]:
            flags = ["crowded"] if (c.get("attempts") or 0) >= 2 or c["comments"] > 30 else []
            leads.append(Lead(NAME, c["id"], c["url"], f"{c['repo']}: {c['title']}", 0, pay_text=f"${c['amount']} bounty",
                              pay_usd=float(c["amount"]), pay_kind="bounty", competition=c.get("attempts") or 0,
                              tags=[f"created {c['created']}", f"comments {c['comments']}"], flags=flags))
    # extra searches: surface candidates the sniper's window may not include (read-only, 3 search calls)
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 14 * 86400))
    have = {l.url for l in leads}; extra = 0
    for q in EXTRA:
        try:
            d = get("https://api.github.com/search/issues?" + urllib.parse.urlencode({"q": f"{q} created:>{since}", "per_page": 50, "sort": "created"}),
                    expect="json", headers=gh_headers(), ua="delphi-lead-scan")
            for it in d.get("items", []):
                amt = max([int(x.replace(",", "")) for x in re.findall(r"\$\s?([\d,]{3,7})", it["title"] + " " + " ".join(l["name"] for l in it["labels"]))] or [0])
                if amt < 100 or it["html_url"] in have: continue
                repo = it["repository_url"].split("/repos/")[1]
                if repo.lower() in SPAM_REPOS or not vetted(repo): continue
                have.add(it["html_url"]); extra += 1
                leads.append(Lead(NAME + "/gh-search", str(it["id"]), it["html_url"], f"{repo}: {it['title']}", 0,
                                  pay_text=f"${amt} (title/label)", pay_usd=float(amt), pay_kind="bounty",
                                  competition=it["comments"], tags=[f"created {it['created_at'][:10]}"], flags=["repo-unvetted"]))
        except FetchError as e: log(NAME, "warn", f"gh search: {e}")
        time.sleep(2)
    STATS.append({"source": NAME, "http": f"sniper rc={r.returncode}", "n_fit": len(leads), "extra_search_hits": extra,
                  "ms": int((time.time() - t0) * 1000)})
    return leads
