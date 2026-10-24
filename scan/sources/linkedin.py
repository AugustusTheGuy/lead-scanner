"""LinkedIn guest job search (public, no login): contract + remote + past 24 h."""
import re, time, html, urllib.parse
from datetime import datetime
from ..core import get, Lead, log, FetchError, STATS

NAME = "linkedin"
QUERIES = ["python contract", "web scraping", "ai automation freelance"]
CARD = re.compile(r'<div class="base-card.*?</li>', re.S)


def parse(page):
    out = []
    for c in re.findall(r"<li>(.*?)</li>", page, re.S):
        url = (re.search(r'href="(https://www\.linkedin\.com/jobs/view/[^"?]+)', c) or [None, ""])[1]
        if not url: continue
        g = lambda rx: html.unescape(re.sub(r"\s+", " ", (re.search(rx, c, re.S) or [None, ""])[1])).strip()
        out.append({"url": url, "id": url.rstrip("/").split("-")[-1], "title": g(r'base-search-card__title">(.*?)<'),
                    "company": g(r'base-search-card__subtitle">.*?>(.*?)<'), "loc": g(r'job-search-card__location">(.*?)<'),
                    "dt": g(r'<time[^>]*datetime="([^"]+)"'), "sal": g(r'job-search-card__salary-info">(.*?)<')})
    return out


def scan(hours=72, live=True):
    t0 = time.time(); rows = {}
    for q in QUERIES:
        for start in (0, 25):
            u = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
                 + urllib.parse.urlencode({"keywords": q, "f_JT": "C", "f_TPR": "r86400", "f_WT": "2", "start": start}))
            try:
                for r in parse(get(u, tries=2)): rows.setdefault(r["id"], r)
            except FetchError as e: log(NAME, "warn", f"{q}@{start}: {e}"); break
            time.sleep(1.2)
    leads, dedupe = [], set()
    for r in rows.values():
        k = (r["company"].lower(), r["title"].lower())
        if k in dedupe: continue
        dedupe.add(k)
        ts = datetime.fromisoformat(r["dt"]).timestamp() if r["dt"] else 0
        leads.append(Lead(NAME, r["id"], r["url"], f"{r['title']} @ {r['company']}", ts, pay_text=r["sal"],
                          body=r["title"], tags=[r["loc"], "contract"], flags=["ft-or-contract-role"]))
    STATS.append({"source": NAME, "http": "ok", "n_raw": len(rows), "n_fit": len(leads), "ms": int((time.time() - t0) * 1000)})
    return leads
