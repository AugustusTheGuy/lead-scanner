"""X leads. The public X tools are MCP tools, not HTTP APIs reachable from Python, so the routine runs
the queries below with the X tools and writes results to state/x_inbox.json; this module scores them.
Bug fixed: the X routine only watched @Prophecy2Profit mentions (alerts, not leads)."""
import json, os, re, time
from datetime import datetime
from ..core import Lead, log, STATS, STATE_DIR

NAME = "x"
QUERIES = [  # 3 extra searches + buyer-intent phrases, -filter:retweets
    '"need a developer" (python OR scraper OR automation) -is:retweet lang:en',
    '"will pay" (bot OR script OR scraper) -is:retweet lang:en',
    '"anyone know" ("telegram bot" OR "discord bot" OR scraper) -is:retweet lang:en',
    '("looking for" OR "need") ("n8n" OR "zapier" OR "make.com") (expert OR freelancer OR dev) -is:retweet lang:en',
    'from:ExpensifyOSS OR "algora" bounty -is:retweet',
]
INBOX = os.path.join(STATE_DIR, "x_inbox.json")
BUYER = re.compile(r"\b(i|we)('m|'re| am| are)? (currently |urgently )?(looking for|need|seeking) (a |an )?(dev|developer|freelancer|programmer|someone)|"
                   r"\bwill pay\b|\bwho can (build|make|code|set ?up)|\bhiring\b.{0,40}(dev|engineer|automation|python)|dm me if you can build", re.I)
SELLER = re.compile(r"\bi build\b|\bneed a developer\?|dm me for|my services|hire me|i help (businesses|you)|thread|🧵|here('| a)re \d+", re.I)
HIRE_BOT = re.compile(r"#hiring #jobs|apply now|job alert|jobs? board|we're hiring:", re.I)


def scan(hours=72, live=True):
    t0 = time.time()
    try: posts = json.load(open(INBOX))
    except Exception: posts = []
    leads = []
    for p in posts:
        txt = p.get("text", "")
        if HIRE_BOT.search(txt) or txt.startswith("RT @") or SELLER.search(txt) or not BUYER.search(txt): continue
        if p.get("author_created_at"):
            age = time.time() - datetime.fromisoformat(p["author_created_at"].replace("Z", "+00:00")).timestamp()
            if age < 30 * 86400: continue  # new accounts = spam/scam risk
        ts = datetime.fromisoformat(p["created_at"].replace("Z", "+00:00")).timestamp() if p.get("created_at") else 0
        leads.append(Lead(NAME, str(p["id"]), f"https://x.com/{p.get('username','i')}/status/{p['id']}", txt[:110], ts,
                          body=txt, author=p.get("username", ""), competition=p.get("reply_count", -1)))
    STATS.append({"source": NAME, "http": "file", "n_raw": len(posts), "n_fit": len(leads), "ms": int((time.time() - t0) * 1000)})
    return leads
