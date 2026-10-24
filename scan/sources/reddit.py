"""Reddit buyers via Arctic Shift (archive, ~0.1 h lag) + best-effort live reddit.com Atom RSS.
ROOT CAUSES of the old '0 buyers' result (verified live 2026-10-24):
 1. ~80% of r/forhire bodies in Arctic Shift are '[removed]' (captured while pending mod approval);
    the old filter (raw/filt.py) required a tech keyword in title+body, so real [Hiring] posts died.
 2. Arctic Shift: comma-separated subreddit=a,b returns [] silently; link_flair_text= is ignored
    (returns For Hire posts); query=/title= full-text can 422 'Timeout. Maybe slow down'; invalid
    field names -> 400. Old pag.py swallowed every exception and wrote empty files.
 3. reddit.com /new.json returns a 403 HTML block page; it was saved as forhire.json, n8n.json,
    hiring.json ... (all identical 189,908-byte files) and read as 'no data'.
 4. Sub list: r/freelance_forhire is not indexed by Arctic Shift (0 rows); help subs
    (r/automation, r/webscraping) have no hiring flair so flair filters can't find buyers there.
 5. leads_seen.txt (903 mixed URLs) hid still-open leads; now NEW/SEEN is a label, not a filter.
"""
import re, time, urllib.parse
from ..core import get, Lead, strip_html, log, FetchError, STATS

NAME = "reddit"
BUYER_SUBS = ["forhire", "hiring", "jobbit", "slavelabour", "DoneDirtCheap", "PythonJobs", "HireaProgrammer",
              "Jobs4Bitcoins", "freelance_forhire"]
HELP_SUBS = ["webscraping", "automation", "n8n", "zapier", "DiscordBots", "Telegram", "smallbusiness",
             "nocode", "googlesheets"]   # r/SaaS dropped after run 2: 0/9 hits were buyers (founder pricing polls)   # sideproject/startups dropped: 0 buyers in 72 h sample, +35 s runtime
AS = "https://arctic-shift.photon-reddit.com/api"
AS_UA = "delphi-lead-scan/2.0 (read-only research; contact via reddit)"
FIELDS = "id,title,selftext,created_utc,author,link_flair_text,num_comments,subreddit"  # NB: "permalink" is NOT a valid Arctic Shift field -> HTTP 400 (the old "fields rejected" bug)
# 3 extra searches (scan_requirements.md §1)
SEARCHES = [("forhire", "Hiring"), ("slavelabour", "TASK")]   # + r/webscraping client-side pay|hire match
NOT_BUYER = re.compile(r"for\s?hire|\[available\]|\[fh\]|\boffer\b|hired\b|closed|filled|seeking work|my services|portfolio", re.I)
BUYER_FLAIR = re.compile(r"^\s*(hiring|task|now hiring|paid|job)\b", re.I)
BUYER_TITLE = re.compile(r"\[(hiring|task|paid|job|hire)\]|\bhiring\b|\blooking (to hire|for (a|an|someone))\b|\bneed (a|an|someone)\b|\bwill pay\b|\bpaid\b|\$\s?\d", re.I)
# help subs: need an explicit hire/pay phrase (not just "$" or "budget": those matched 117 SaaS/SideProject brag posts)
INTENT = re.compile(r"looking for (someone|a (dev|developer|freelancer|programmer)) to|will pay|happy to pay|willing to pay|"
                    r"my budget|paid (gig|project|task|work)|hire (someone|a dev|a developer|a freelancer|a programmer)|"
                    r"looking to hire|\[hiring\]|\[paid\]|\[task\]", re.I)
ZW = re.compile("[\u200b-\u200f\u2060\ufeff]")


def classify(sub, flair, title, body):
    flair = (flair or "").strip(); title = ZW.sub("", title or "")
    if NOT_BUYER.search(flair) or re.match(r"\s*[\[(]?\s*(for\s?hire|fh|offer|available)\b", title, re.I): return False
    if sub.lower() in {s.lower() for s in BUYER_SUBS}:
        return bool(BUYER_FLAIR.match(flair) or BUYER_TITLE.search(title))
    tb = f"{title}\n{body}"
    return (bool(INTENT.search(tb)) and bool(re.search(r"build|automat|scrap|integrat|bot\b|script|workflow|website|app\b|dashboard", tb, re.I))
            and not re.search(r"\bi (built|made|launched)\b", title, re.I)
            and not re.search(r"would you (personally )?(be )?willing to pay|would (you|anyone) pay for", tb, re.I))


def arctic(kind, sub, after, extra=""):
    out, before = [], None
    for _ in range(6):
        f = FIELDS if kind == "posts" else "id,body,created_utc,author,link_id,subreddit"
        u = (f"{AS}/{kind}/search?subreddit={sub}&after={after}&limit=100&sort=desc&fields={f}{extra}"
             + (f"&before={before}" if before else ""))
        d = get(u, ua=AS_UA, expect="json", tries=2)
        if d.get("error"): raise FetchError(200, u, d["error"])
        rows = d.get("data") or []
        out += rows
        if len(rows) < 100: break
        before = min(p["created_utc"] for p in rows); time.sleep(0.6)
    return out


def parse_atom(xml):
    rows = []
    for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        g = lambda rx: (re.search(rx, e, re.S) or [None, ""])[1]
        link = g(r'<link href="([^"]+)"'); pid = (re.search(r"/comments/([a-z0-9]+)", link) or [None, ""])[1]
        rows.append({"id": pid, "url": link, "title": strip_html(g(r"<title>(.*?)</title>")),
                     "author": g(r"<name>/?u/(.*?)</name>"), "sub": g(r'<category term="([^"]+)"'),
                     "published": g(r"<published>(.*?)</published>"),
                     "body": strip_html(g(r"<content[^>]*>(.*?)</content>"))[:4000]})
    return rows


def live_bodies():
    """One best-effort RSS call (403/429 from the box are common) to fill '[removed]' bodies."""
    try:
        x = get("https://www.reddit.com/r/" + "+".join(BUYER_SUBS[:7]) + "/new/.rss?limit=100", expect="xml", tries=1)
        return {r["id"]: r for r in parse_atom(x)}
    except FetchError as e:
        log(NAME, "warn", f"live rss skipped: {e}"); return {}


def to_lead(p, live):
    sub = p.get("subreddit", ""); body = p.get("selftext") or ""; flags = []
    if body in ("[removed]", "[deleted]", ""):
        lr = live.get(p["id"])
        if lr and lr["body"] and "[removed]" not in lr["body"][:20]: body = lr["body"]
        elif body: flags.append("removed")
    return Lead(NAME + "/" + sub, p["id"], f"https://www.reddit.com/r/{sub}/comments/{p['id']}/", p.get("title", ""),
                p.get("created_utc", 0), body=body[:4000], author=p.get("author", ""),
                competition=p.get("num_comments", -1), tags=[(p.get("link_flair_text") or "").strip()], flags=flags)


def scan(hours=72, live=True):
    t0 = time.time(); after = int(time.time()) - hours * 3600
    posts, ok, miss = {}, 0, 0
    for sub in BUYER_SUBS + HELP_SUBS:                   # expansion 1+2: per-sub loop, wider sub list
        try:
            rows = arctic("posts", sub, after); ok += 1
            for p in rows: posts[p["id"]] = p
        except FetchError as e:
            miss += 1; log(NAME, "warn", f"arctic {sub}: {e}")
        time.sleep(0.8)
    for sub, t in SEARCHES:                                # extra searches 1-2 (title= with subreddit=)
        try:
            for p in arctic("posts", sub, after, f"&title={t}"): posts[p["id"]] = p
        except FetchError as e:
            log(NAME, "warn", f"arctic title search {sub}/{t}: {e}")
        time.sleep(0.8)
    live_rows = live_bodies() if live else {}
    leads = [to_lead(p, live_rows) for p in posts.values()
             if classify(p.get("subreddit", ""), p.get("link_flair_text"), p.get("title", ""), p.get("selftext") or "")]
    # expansion 3: comment scan on help subs (buyers often ask inside threads)
    cx = re.compile(r"(looking for someone to (build|make|automate|scrape)|(will|happy to|willing to) pay (someone|for|a dev)|"
                    r"my budget is|hire (a|someone) to (build|automate|scrape|write))", re.I)
    nc = 0
    for sub in ["webscraping", "automation", "n8n", "smallbusiness"]:
        try:
            for c in arctic("comments", sub, int(time.time()) - min(hours, 48) * 3600):
                b = c.get("body") or ""
                if cx.search(b) and not re.search(r"i (can|could) (build|help|do)|dm me|hire me|i'm a dev|i build", b, re.I):
                    lid = (c.get("link_id") or "").replace("t3_", ""); nc += 1
                    leads.append(Lead(NAME + "/" + sub, "c" + c["id"], f"https://www.reddit.com/r/{sub}/comments/{lid}/_/{c['id']}/",
                                      "[comment] " + b[:90].replace("\n", " "), c.get("created_utc", 0), body=b[:3000],
                                      author=c.get("author", ""), tags=["comment"]))
        except FetchError as e:
            log(NAME, "warn", f"arctic comments {sub}: {e}")
        time.sleep(0.8)
    STATS.append({"source": NAME, "http": f"{ok}/{ok + miss} subs ok", "n_raw": len(posts), "n_live_rss": len(live_rows),
                  "n_fit": len(leads), "comment_hits": nc, "ms": int((time.time() - t0) * 1000)})
    return leads
