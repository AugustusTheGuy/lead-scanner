"""Braintrust public jobs API, paginated until next is null."""
import re, time
from datetime import datetime
from ..core import get, Lead, log, FetchError, STATS

NAME = "braintrust"
FIT = re.compile(r"engineer|developer|python|automation|ai\b|llm|full.?stack|backend|data|software", re.I)


def scan(hours=72, live=True):
    t0 = time.time(); u = "https://app.usebraintrust.com/api/jobs/?page_size=50"; rows = []
    for _ in range(10):
        try: d = get(u, expect="json")
        except FetchError as e: log(NAME, "warn", str(e)); break
        rows += d.get("results", []); u = d.get("next")
        if not u: break
        u = u.replace("http://", "https://")
    leads = []
    for j in rows:
        skills = " ".join(s["name"] for s in j.get("main_skills") or [])
        if not FIT.search(j["title"] + " " + skills): continue
        if (j.get("openings_left") or 1) <= 0: continue
        locs = " ".join(x.get("location", "") for x in j.get("locations") or [])
        if locs and not re.search(r"United States|Anywhere|Americas|North America|Worldwide", locs): continue
        hi = float(j.get("budget_maximum_usd") or j.get("budget_minimum_usd") or 0)
        kind = "hourly" if j.get("payment_type") == "hourly" else "salary" if hi > 20000 else "fixed"
        if kind == "hourly" and hi < 40: continue
        ts = datetime.fromisoformat(j["created"].replace("Z", "+00:00")).timestamp()
        leads.append(Lead(NAME, str(j["id"]), f"https://app.usebraintrust.com/jobs/{j['id']}/", j["title"], ts,
                          pay_text=f"${j.get('budget_minimum_usd')}-{j.get('budget_maximum_usd')} {j.get('payment_type')}",
                          pay_usd=hi, pay_kind=kind, author=(j.get("employer") or {}).get("name", ""),
                          tags=[skills[:80], f"{j.get('expected_hours_per_week')}h/wk", j.get("job_type") or ""],
                          flags=["needs-approved-profile"]))
    STATS.append({"source": NAME, "http": "ok", "n_raw": len(rows), "n_fit": len(leads), "ms": int((time.time() - t0) * 1000)})
    return leads
