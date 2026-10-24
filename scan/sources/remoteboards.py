"""RemoteOK API + We Work Remotely RSS; contract/freelance/part-time only."""
import re, time
from email.utils import parsedate_to_datetime
from ..core import get, Lead, log, FetchError, STATS, strip_html

NAME = "remote"
GIG = re.compile(r"contract|freelanc|part[- ]?time|hourly|consult", re.I)
FIT = re.compile(r"python|scrap|automation|\bbot|\bai\b|llm|rag\b|full[- ]?stack|typescript|react|node|django|fastapi|backend", re.I)
WWR = ["remote-back-end-programming-jobs", "remote-full-stack-programming-jobs", "remote-programming-jobs"]


def scan(hours=72, live=True):
    t0 = time.time(); leads = []; n = 0
    try:
        for j in get("https://remoteok.com/api", expect="json")[1:]:
            n += 1
            txt = f"{j.get('position')} {' '.join(j.get('tags') or [])} {strip_html(j.get('description') or '')[:1500]}"
            if not (GIG.search(txt) and FIT.search(txt)): continue
            if time.time() - int(j.get("epoch") or 0) > hours * 3600 * 3: continue
            pay = j.get("salary_max") or j.get("salary_min") or 0
            leads.append(Lead(NAME + "/remoteok", str(j["id"]), j.get("url") or f"https://remoteok.com/remote-jobs/{j['id']}",
                              f"{j.get('position')} @ {j.get('company')}", int(j.get("epoch") or 0),
                              pay_text=f"${j.get('salary_min')}-{j.get('salary_max')}/yr" if pay else "", pay_usd=float(pay),
                              pay_kind="salary" if pay else "unknown", body=txt[:2000], tags=(j.get("tags") or [])[:6]))
    except FetchError as e: log(NAME, "warn", f"remoteok: {e}")
    for c in WWR:
        try:
            x = get(f"https://weworkremotely.com/categories/{c}.rss", expect="xml")
            for it in re.findall(r"<item>(.*?)</item>", x, re.S):
                n += 1
                g = lambda t: strip_html((re.search(rf"<{t}>(.*?)</{t}>", it, re.S) or [None, ""])[1].replace("<![CDATA[", "").replace("]]>", ""))
                txt = g("title") + " " + g("type") + " " + g("description")[:1500]
                if not (GIG.search(g("type") + " " + g("title")) and FIT.search(txt)): continue
                ts = parsedate_to_datetime(g("pubDate")).timestamp() if g("pubDate") else 0
                leads.append(Lead(NAME + "/wwr", g("guid") or g("link"), g("link"), g("title"), ts, body=txt[:2000], tags=[g("type")]))
        except FetchError as e: log(NAME, "warn", f"wwr {c}: {e}")
    seen = set(); leads = [l for l in leads if not (l.url in seen or seen.add(l.url))]
    STATS.append({"source": NAME, "http": "ok", "n_raw": n, "n_fit": len(leads), "ms": int((time.time() - t0) * 1000)})
    return leads
