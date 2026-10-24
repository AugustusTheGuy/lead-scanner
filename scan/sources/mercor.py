"""Mercor public explore feed (aws.api.mercor.com/work/listings-explore-page)."""
import re, time
from datetime import datetime, timezone
from ..core import get, Lead, log, FetchError, STATS

NAME = "mercor"
ENG = re.compile(r"software|engineer|developer|python|backend|full.?stack|typescript|coding|code|agent|llm|rag|eval|data", re.I)
SEARCHES = [r"python|backend", r"full.?stack|typescript", r"agent|llm|rag|eval"]
BAD = re.compile(r"mechanical|electrical|civil|materials|clinical|industrial|firmware|hardware|atomistic|cad\b|"
                 r"network engineer|mental health|medical|biolog|chemi|physic|finance expert|legal|radiolog|physician|nurse|attorney|lawyer|md\b|phd|board.certified|doctor|pharmac|actuar|cpa\b|banker|consultant at", re.I)


def scan(hours=72, live=True):
    t0 = time.time()
    d = get("https://aws.api.mercor.com/work/listings-explore-page", expect="json", timeout=30)
    ls = d.get("listings", []); leads = []
    for l in ls:
        if l.get("status") != "active" or l.get("disableApplications"): continue
        t = f"{l['title']} {l.get('listingDomain') or ''}"
        if not ENG.search(t) or BAD.search(l["title"]): continue
        inel = str(l.get("ineligibleLocation") or "") + str(l.get("ineligibleResidenceLocation") or "")
        el = str(l.get("eligibleLocation") or "") + str(l.get("eligibleResidenceLocation") or "")
        if "USA" in inel or (el and el != "None" and "US" not in el and "United States" not in el): continue
        if re.search(r"\((india|latam|brazil|mexico|philippines|europe|uk|canada|apac|emea)[^)]*\)", l["title"], re.I): continue
        rmin, rmax = l.get("rateMin") or 0, l.get("rateMax") or 0
        freq = (l.get("payRateFrequency") or "hourly").lower()
        if l.get("payRateFrequency") == "hourly" and rmax and rmax < 40: continue
        posted = datetime.fromisoformat(l["postedAt"]).replace(tzinfo=timezone.utc).timestamp() if l.get("postedAt") else 0
        rc = l.get("recentCandidatesCount") or 0; slots = l.get("remainingSlots") or 0
        body = l.get("description") or ""
        flags = ["gated"] if re.search(r"must (work|have).{0,40}(years|phd|research)|\b(5|6|7|8|10)\+ years", body[:800], re.I) else []
        leads.append(Lead(NAME, l["listingId"], f"https://work.mercor.com/jobs/{l['listingId']}", l["title"], posted,
                          pay_text=f"${rmin:g}-{rmax:g}/{l.get('payRateFrequency') or 'hr'}", pay_usd=float(rmax or rmin),
                          pay_kind="hourly" if freq == "hourly" else "salary" if freq in ("yearly", "annual", "annually") else "fixed",
                          body=body[:3000],
                          competition=rc, author=l.get("companyName") or "",
                          tags=[f"slots {slots}", f"recent cands {rc}", f"{l.get('hoursPerWeek')}h/wk"], flags=flags))
    STATS.append({"source": NAME, "http": "ok", "n_raw": len(ls), "n_fit": len(leads), "ms": int((time.time() - t0) * 1000)})
    return leads
