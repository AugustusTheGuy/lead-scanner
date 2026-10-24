"""Arc.dev public job pages: parse __NEXT_DATA__ (not page text)."""
import re, json, time
from ..core import get, Lead, log, FetchError, STATS

NAME = "arc"
PAGES = ["python", "python?jobTypes=freelance", "web-scraping", "ai", "full-stack"]  # last 3 = extra searches


def parse(page):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m: return []
    pp = json.loads(m.group(1))["props"]["pageProps"]
    return (pp.get("arcJobs") or []) + (pp.get("externalJobs") or [])


def scan(hours=72, live=True):
    t0 = time.time(); jobs = {}; ok = 0
    for p in PAGES:
        try:
            for j in parse(get(f"https://arc.dev/remote-jobs/{p}")): jobs[j["randomKey"]] = j
            ok += 1
        except FetchError as e: log(NAME, "warn", f"{p}: {e}")
        time.sleep(0.5)
    leads = []
    for j in jobs.values():
        jt = j.get("jobType") or ""
        hr = j.get("maxHourlyRate") or j.get("minHourlyRate")
        sal = j.get("maxAnnualSalary") or j.get("minAnnualSalary")
        if jt not in ("freelance", "contract", "part-time", "parttime") and not hr: continue
        if hr and hr < 40: continue
        rc = j.get("requiredCountries") or []
        if rc and "US" not in rc: continue
        url = f"https://arc.dev/remote-jobs/details/{j.get('urlString')}-{j['randomKey']}"
        leads.append(Lead(NAME, j["randomKey"], url, j["title"], float(j.get("postedAt") or 0),
                          pay_text=f"${j.get('minHourlyRate')}-{j.get('maxHourlyRate')}/h" if hr else (f"${sal}/yr" if sal else ""),
                          pay_usd=float(hr or sal or 0), pay_kind="hourly" if hr else "salary",
                          tags=[jt, j.get("experienceLevel") or ""], flags=["needs-approved-profile"]))
    STATS.append({"source": NAME, "http": f"{ok}/{len(PAGES)}", "n_raw": len(jobs), "n_fit": len(leads), "ms": int((time.time() - t0) * 1000)})
    return leads
