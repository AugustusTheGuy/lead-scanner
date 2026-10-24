"""Superteam Earn. Bug fixed: endpoint now 308-redirects (needs -L); content/meme bounties dominated."""
import re, time
from datetime import datetime
from ..core import get, Lead, log, FetchError, STATS

NAME = "superteam"
DEV = re.compile(r"build|dev|bot|api|sdk|integrat|tool|dashboard|app\b|agent|ai\b|script|smart contract|program|audit|frontend|backend|route|challenge", re.I)
SEARCHES = ["type=project", "type=bounty", "type=hackathon"]


def scan(hours=72, live=True):
    t0 = time.time(); seen = {}
    for q in ["take=100"] + SEARCHES + ["category=Development"]:
        try:
            for l in get(f"https://earn.superteam.fun/api/listings?{q}&take=100", expect="json"): seen[l["id"]] = l
        except FetchError as e: log(NAME, "warn", f"{q}: {e}")
    leads = []
    for l in seen.values():
        dl = datetime.fromisoformat(l["deadline"].replace("Z", "+00:00")).timestamp() if l.get("deadline") else 0
        if l.get("status") != "OPEN" or (dl and dl - time.time() < 48 * 3600): continue
        if not DEV.search(l["title"]): continue
        amt = l.get("rewardAmount") or l.get("maxRewardAsk") or 0
        subs = (l.get("_count") or {}).get("Submission", -1)
        flags = ["contest"] if l["type"] in ("bounty", "hackathon") else []
        if amt and amt < 100: continue
        leads.append(Lead(NAME, l["id"], f"https://earn.superteam.fun/listing/{l['slug']}", l["title"], 0,
                          pay_text=f"{amt} {l.get('token')} ({l['type']})", pay_usd=float(amt or 0),
                          pay_kind="bounty", competition=subs, author=(l.get("sponsor") or {}).get("name", ""),
                          tags=[f"deadline {l['deadline'][:10]}", l.get("agentAccess", "")], flags=flags))
    STATS.append({"source": NAME, "http": "ok", "n_raw": len(seen), "n_fit": len(leads), "ms": int((time.time() - t0) * 1000)})
    return leads
