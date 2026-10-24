"""Freelancer.com public projects API. Bug fixed: query= is ignored by the API (returned unrelated
projects with 60-213 bids); now filters by skill IDs, normalizes currency, caps bids."""
import time
from ..core import get, Lead, log, FetchError, STATS

NAME = "freelancer"
SKILLS = {13: "Python", 95: "Web Scraping", 1977: "Automation", 2917: "AI Chatbot", 2918: "Bot Development",
          1077: "Data Extraction", 500: "Node.js", 759: "React.js"}
SEARCHES = [[95], [13, 1977], [2917]]  # 3 extra: Web Scraping; Python+Automation; AI Chatbot
MAX_BIDS = 15


def fetch(job_ids, n=100):
    q = "&".join(f"jobs[]={j}" for j in job_ids)
    u = (f"https://www.freelancer.com/api/projects/0.1/projects/active/?{q}&limit={n}&full_description=true"
         f"&job_details=true&user_details=true&user_status=true&sort_field=time_updated")
    return get(u, expect="json")["result"]


def scan(hours=72, live=True):
    t0 = time.time(); seen = {}; n_raw = 0
    for ids in [list(SKILLS)] + SEARCHES:
        try:
            res = fetch(ids); ps = res.get("projects", []); n_raw += len(ps)
            users = res.get("users") or {}
            for p in ps: p["_owner"] = users.get(str(p.get("owner_id"))) or {}; seen[p["id"]] = p
        except FetchError as e: log(NAME, "warn", f"{ids}: {e}")
        time.sleep(0.5)
    leads = []
    for p in seen.values():
        bids = (p.get("bid_stats") or {}).get("bid_count", 0)
        if bids > MAX_BIDS or time.time() - p["time_submitted"] > hours * 3600: continue
        cur = p["currency"]; rate = cur.get("exchange_rate") or 1
        b = p.get("budget") or {}; hi = (b.get("maximum") or b.get("minimum") or 0) * rate
        kind = "hourly" if p.get("type") == "hourly" else "fixed"
        if (kind == "fixed" and hi < 100) or (kind == "hourly" and hi < 15): continue
        st = (p["_owner"].get("status") or {})
        flags = ["needs-track-record"]  # new Freelancer accounts with 0 reviews rarely win; bids cost membership
        if not st.get("payment_verified"): flags.append("client-unverified")
        leads.append(Lead(NAME, str(p["id"]), f"https://www.freelancer.com/projects/{p['seo_url']}", p["title"],
                          p["time_submitted"], pay_text=f"{cur['sign']}{b.get('minimum')}-{b.get('maximum')} {cur['code']} {kind}",
                          pay_usd=hi, pay_kind=kind, body=p.get("description") or "", competition=bids,
                          tags=[j["name"] for j in p.get("jobs", [])][:6], flags=flags))
    STATS.append({"source": NAME, "http": "ok", "n_raw": n_raw, "n_unique": len(seen), "n_fit": len(leads),
                  "ms": int((time.time() - t0) * 1000)})
    return leads
