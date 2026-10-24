"""Expensify/App 'Help Wanted' (paid via Upwork). Fix: search by updated:, then read the issue
events for the time the Help Wanted label was added (created: missed issues labelled later)."""
import re, time, urllib.parse
from datetime import datetime
from ..core import get, Lead, log, FetchError, STATS
from .algora import gh_headers

NAME = "expensify"
QS = ['repo:Expensify/App label:"Help Wanted" label:External is:open is:issue',
      'repo:Expensify/App label:"Help Wanted" label:Daily is:open is:issue',     # 3 extra searches
      'repo:Expensify/App label:"Help Wanted" label:Weekly is:open is:issue',
      'repo:Expensify/App label:"Help Wanted" is:open is:issue "[$" in:title']


def scan(hours=72, live=True, max_events=8):
    t0 = time.time(); items = {}
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))
    for q in QS:
        try:
            d = get("https://api.github.com/search/issues?" + urllib.parse.urlencode({"q": f"{q} updated:>={since}", "per_page": 100, "sort": "updated"}),
                    expect="json", headers=gh_headers(), ua="delphi-lead-scan")
            for it in d.get("items", []): items[it["id"]] = it
        except FetchError as e: log(NAME, "warn", f"search: {e}")
        time.sleep(2)
    leads = []; ev = 0
    for it in sorted(items.values(), key=lambda i: i["updated_at"], reverse=True):
        amt = max([int(x.replace(",", "")) for x in re.findall(r"\[\$([\d,]+)\]", it["title"])] or [0])
        if amt < 100: continue
        if any(l["name"].lower() in ("reviewing", "awaiting payment", "on hold") for l in it["labels"]): continue
        if it.get("assignees") and len(it["assignees"]) >= 3: pass
        labeled = 0
        if ev < max_events:  # core API budget: 60/h unauthenticated
            try:
                evs = get(it["events_url"] + "?per_page=100", expect="json", headers=gh_headers(), ua="delphi-lead-scan"); ev += 1
                hw = [e for e in evs if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == "Help Wanted"]
                if hw: labeled = datetime.fromisoformat(hw[-1]["created_at"].replace("Z", "+00:00")).timestamp()
            except FetchError as e: log(NAME, "warn", f"events: {e}")
        flags = ["crowded"] if it["comments"] > 25 else []
        leads.append(Lead(NAME, str(it["number"]), it["html_url"], it["title"], labeled or 0, pay_text=f"${amt} (Upwork)", body="Expensify App: React Native + TypeScript (full-stack JS) bug fix",
                          pay_usd=float(amt), pay_kind="bounty", competition=it["comments"],
                          tags=[f"updated {it['updated_at'][:16]}Z", "help-wanted label time" if labeled else "label time unknown"], flags=flags))
    STATS.append({"source": NAME, "http": "ok", "n_raw": len(items), "n_fit": len(leads), "ms": int((time.time() - t0) * 1000)})
    return leads
