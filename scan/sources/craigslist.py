"""Craigslist computer gigs. Needs redirects (-L) + browser UA; parse li.cl-static-search-result.
Bugs fixed: 3 metros (losangeles/newyork/sfbay root pages) were saved as 0-byte files and */ggg as
248-byte redirect stubs (no -L) and treated as 'no gigs'; the static list has NO post time, so the old
scan reported undated leads; travel-MLM spam ('build from home') was not filtered; the same ad
cross-posted in many metros was reported once per metro."""
import re, time, html
from ..core import get, Lead, log, FetchError, STATS, strip_html

NAME = "craigslist"
METROS = ["seattle", "portland", "sfbay", "losangeles", "sandiego", "newyork", "austin", "chicago", "boston", "denver"]
PATHS = ["/search/cpg", "/search/cpg?query=python", "/search/sof?query=contract%20python"]
SEARCHES = ["/search/cpg?query=scraper", "/search/cpg?query=automation", "/search/cpg?query=chatbot"]  # 3 extra
LI = re.compile(r'<li class="cl-static-search-result"[^>]*title="([^"]*)">\s*<a href="([^"]+)">(.*?)</li>', re.S)
SPAM = re.compile(r"training|career|course|bootcamp|class(es)?\b|certification|learn to|build from home|travel business|be your own boss|text me|gift ?card|cashier|check|mystery shop|"
                  r"crypto|forex|onlyfans|\$\d{3,}/day|earn \$|work from home opportunity", re.I)
TECH = re.compile(r"python|scrap|automat|bot\b|ai\b|chatbot|developer|programmer|web ?site|app\b|api|excel|data|"
                  r"software|wordpress|shopify|react|node|javascript|database|sql|integrat|zapier|n8n|script", re.I)


def parse_list(page):
    out = []
    for title, url, inner in LI.findall(page):
        price = (re.search(r'<div class="price">([^<]*)</div>', inner) or [None, ""])[1].strip()
        loc = strip_html((re.search(r'<div class="location">(.*?)</div>', inner, re.S) or [None, ""])[1])
        pid = (re.search(r"/([A-Za-z0-9]+?)(?:\.html)?$", url) or [None, url])[1]
        out.append({"id": pid, "url": url, "title": html.unescape(title), "price": price, "loc": loc})
    return out


def parse_view(page):
    t = (re.search(r'<time class="date timeago" datetime="([^"]+)"', page) or [None, ""])[1]
    body = strip_html((re.search(r'<section id="postingbody">(.*?)</section>', page, re.S) or [None, ""])[1])
    attrs = strip_html((re.search(r'<div class="attrgroup">(.*?)</div>\s*</div>', page, re.S) or [None, ""])[1])
    comp = (re.search(r"compensation:\s*([^\n]{1,80})", attrs, re.I) or [None, ""])[1].strip()
    from datetime import datetime
    ts = 0
    if t:
        try: ts = datetime.fromisoformat(t).timestamp()
        except Exception: pass
    return ts, body.replace("QR Code Link to This Post", "").strip(), comp


def scan(hours=72, live=True, max_views=30):
    t0 = time.time(); rows, ok, miss = {}, 0, 0
    for m in METROS:
        for p in PATHS + SEARCHES:
            try:
                page = get(f"https://{m}.craigslist.org{p}", timeout=20, tries=2); ok += 1
                for r in parse_list(page):
                    key = re.sub(r"\W+", "", r["title"].lower())[:60]  # expansion 5: cross-metro dedupe
                    if key not in rows: r["metro"] = m; rows[key] = r
            except FetchError as e:
                miss += 1; log(NAME, "warn", f"{m}{p}: {e}")
            time.sleep(0.3)
    cands = [r for r in rows.values() if not SPAM.search(r["title"]) and TECH.search(r["title"])]
    leads = []
    for r in cands[:max_views]:  # fetch post page for date/body/compensation (static list has no date)
        try:
            ts, body, comp = parse_view(get(r["url"], timeout=20, tries=2))
        except FetchError as e:
            log(NAME, "warn", f"view {r['url']}: {e}"); continue
        if ts and time.time() - ts > hours * 3600 * 4: continue  # CL gigs live ~30 days; keep <=12 days
        if SPAM.search(body[:1500]): continue
        flags = [] if re.search(r"remote|anywhere|online", body + r["title"], re.I) else ["local-only?"]
        pay = comp or (r["price"] if r["price"] not in ("", "$0") else "")
        leads.append(Lead(NAME + "/" + r["metro"], r["id"], r["url"], r["title"], ts, pay_text=pay, body=body[:3000],
                          tags=[r["loc"]], flags=flags))
        time.sleep(0.3)
    STATS.append({"source": NAME, "http": f"{ok}/{ok + miss} pages ok", "n_raw": len(rows), "n_tech": len(cands),
                  "n_fit": len(leads), "ms": int((time.time() - t0) * 1000)})
    return leads
