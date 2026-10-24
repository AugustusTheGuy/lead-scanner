"""Shared HTTP, Lead model, scoring, seen-state. Stdlib only. Read-only: GET requests only."""
import json, os, re, time, math, gzip, urllib.request, urllib.error, urllib.parse
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "state")
OUT_DIR = os.path.join(HERE, "out")
LEGACY_DIR = os.environ.get("LEAD_SCANNER_LEGACY_DIR", HERE)
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
# Optional author blocklist: comma-separated usernames in LEAD_SCANNER_BLOCKLIST (none shipped).
SCAMS = {u.strip().lower() for u in os.environ.get("LEAD_SCANNER_BLOCKLIST", "").split(",") if u.strip()}
LOG = []  # (source, level, msg) collected for the report


STATS = []  # structured per-source lines {source,http,n_raw,n_fresh,n_fit,ms}


def log(src, level, msg):
    LOG.append((src, level, msg))


class FetchError(Exception):
    def __init__(self, code, url, msg=""):
        super().__init__(f"HTTP {code} {url} {msg}"[:300]); self.code = code


def get(url, *, ua=BROWSER_UA, tries=3, timeout=20, expect=None, min_gap=0.0, headers=None):
    """GET with UA, redirects, gzip, backoff on 408/422/429/5xx. Raises FetchError.
    expect='json' -> parsed JSON; rejects HTML block pages served with 200/403 (old bug: block
    page saved as forhire.json). expect='xml' -> must look like XML."""
    last = None
    for a in range(tries):
        if min_gap: time.sleep(min_gap)
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip",
                                                   "Accept": "*/*", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip": body = gzip.decompress(body)
                text = body.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = FetchError(e.code, url, e.read()[:200].decode("utf-8", "replace"))
            if e.code in (408, 422, 429, 500, 502, 503, 504) and a < tries - 1:
                ra = e.headers.get("retry-after")
                wait = 10 if e.code == 422 else (float(ra) if ra and ra.isdigit() else 4 * 2 ** a)
                log("http", "retry", f"{e.code} {url[:90]} wait {min(wait, 30):.0f}s")
                time.sleep(min(wait, 30)); continue
            raise last
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = FetchError(0, url, str(e))
            if a < tries - 1: time.sleep(3 * (a + 1)); continue
            raise last
        if expect == "json":
            s = text.lstrip()
            if not s or s[0] not in "[{":
                raise FetchError(200, url, "non-JSON body (block page?)")
            return json.loads(text)
        if expect == "xml" and not text.lstrip().startswith("<?xml") and "<feed" not in text[:500] and "<rss" not in text[:500]:
            raise FetchError(200, url, "non-XML body")
        return text
    raise last or FetchError(0, url, "exhausted")


@dataclass
class Lead:
    source: str
    id: str
    url: str
    title: str
    posted_utc: float            # epoch seconds; 0 = unknown
    pay_text: str = ""           # pay as shown by the poster
    pay_usd: float = 0.0         # best numeric estimate (project total, or hourly rate)
    pay_kind: str = ""           # fixed | hourly | salary | bounty | unknown
    body: str = ""
    author: str = ""
    competition: int = -1        # comments / bids / submissions; -1 unknown
    tags: list = field(default_factory=list)
    flags: list = field(default_factory=list)   # caveats (removed, gated, scam-risk, ...)
    is_buyer: bool = True
    # filled by score()
    fit: float = 0.0
    p_win: float = 0.0
    hours: float = 0.0
    usd_per_hour: float = 0.0
    rank: float = 0.0
    new: bool = True

    def posted_pt(self):
        if not self.posted_utc: return "unknown"
        return datetime.fromtimestamp(self.posted_utc, PT).strftime("%a %b %d %-I:%M %p PT")

    def age_h(self):
        return (time.time() - self.posted_utc) / 3600 if self.posted_utc else 999


SKILLS = {  # keyword -> weight for the user's stack
    r"\bpython\b": 3, r"scrap(e|er|ing)|crawl|data extraction|extract data": 3, r"automat": 3,
    r"\bbots?\b|discord|telegram|slack bot": 2.5, r"\bn8n\b|zapier|make\.com|webhook|integrat": 2.5,
    r"\bai\b|\bllm|gpt|openai|claude|\brag\b|chatbot|agent|langchain|embedding|vector": 2.5,
    r"\bapi\b|fastapi|flask|django|backend": 2, r"full[- ]?stack|react|next\.?js|node|typescript|javascript": 1.5,
    r"google sheets|excel|spreadsheet|csv|pdf|ocr|data clean": 1.5, r"postgres|sql|supabase|firebase": 1,
    r"stripe|shopify|wordpress|chrome extension": 1, r"\bsolana|web3|smart contract|rust\b": 0.5,
}
OFF = (r"video edit|ugc|thumbnail|voice ?over|translator|translation|cleaner|mover|handyman|truck|driver|"
       r"nurse|radiolog|physician|attorney|lawyer|accountant|cpa\b|tutor|model(ing)? |onlyfans|"
       r"photograph|illustrat|logo design|graphic design|animator|motion graphic|cold call|appointment setter|"
       r"closer\b|sales rep|commission only|recruit(er|ing) (only|for)|chef|caregiver|security clearance|"
       r"secret clearance|ts/sci|on-?site only|tax|bookkeep|content creat|tiktok creat|influencer|voice actor|"
       r"singer|musician|writer|copywrit|ghostwrit|essay|homework|exam|customer support|customer service|"
       r"virtual assistant|\bva\b|data entry|sdr\b|marketing specialist|social media|google ads|clipping")
MIDDLEMAN = (r"referral|talent (network|outsourcing)|outsourcing agency|agency connecting|dm sent|sign-?up link|"
             r"onboarding (coding )?test|i'?ll send (over )?the (direct )?(link|sign)|join ?us\b|circecareer")
SCAM_RX = (r"upfront fee|registration fee|pay (us|a fee) first|send (me )?(your )?(bank|card)|"
           r"build from home|travel business|be your own boss|no experience needed.*\$\d{3,}/day|"
           r"check cashing|reshipp|crypto (recovery|investment)|whatsapp only|telegram only|"
           r"gift card|money mule|mlm|work from home.*earn \$\d{3,} daily")
GATES = (r"(\b(7|8|9|10|12|15)\+? ?years)|phd|board[- ]certified|licensed|clearance|"
         r"must be (located|based) in (?!the us|usa|united states|us\b)|on-?site|relocat")

MONEY = re.compile(r"(?:usd\s?)?\$\s?(\d{1,3}(?:[,\d]{0,9})(?:\.\d+)?)\s?(k\b)?\s*(?:-|–|to)?\s*\$?\s?(\d{1,3}(?:[,\d]{0,9})(?:\.\d+)?)?\s?(k\b)?\s*(/\s?h(?:ou)?r|per hour|an hour|/hr|hourly|/h\b)?", re.I)


def parse_pay(text):
    """Return (usd, kind, shown). Takes the max figure; hourly if /hr. Ignores $0."""
    best, kind, shown = 0.0, "unknown", ""
    for m in MONEY.finditer(text or ""):
        def num(g, k):
            if not g: return 0.0
            v = float(g.replace(",", "")); return v * 1000 if k else v
        lo, hi = num(m.group(1), m.group(2)), num(m.group(3), m.group(4))
        v = max(lo, hi)
        if v <= 0 or v > 5_000_000: continue
        k = "hourly" if m.group(5) else "fixed"
        if k == "fixed" and v >= 20000: k = "salary"
        score = v * (40 if k == "hourly" else 1)
        if score > (best * (40 if kind == "hourly" else 1)):
            best, kind, shown = v, k, m.group(0).strip()
    return best, kind, shown


def fit_score(text):
    t = (text or "").lower()
    s = sum(w for rx, w in SKILLS.items() if re.search(rx, t))
    off = bool(re.search(OFF, t))
    return min(s, 10.0), off


def score(lead: Lead):
    """Expected $/hour x win probability for: Python/automation/scraping/bots/AI-RAG/full-stack,
    ~4 yrs exp, $0 platform track record, no Upwork Connects. Heuristic, documented in README."""
    text = f"{lead.title}\n{lead.body}"
    t = text.lower()
    fit, off = fit_score(text)
    lead.fit = fit
    if (off and fit < 4) or fit < 1.5: lead.flags.append("off-stack")
    if re.search(SCAM_RX, t) or (lead.author or "").lower() in SCAMS: lead.flags.append("scam-risk")
    if re.search(GATES, t): lead.flags.append("gated")
    if re.search(MIDDLEMAN, t) and not lead.source.startswith(("mercor", "braintrust", "arc")): lead.flags.append("middleman")
    if not lead.pay_usd:
        lead.pay_usd, lead.pay_kind, shown = parse_pay(text)
        if shown and not lead.pay_text: lead.pay_text = shown
    # hours to deliver: crude by kind and amount
    pay = lead.pay_usd; kind = lead.pay_kind
    if kind == "fixed" and re.search(r"(/|per |a )(mo\b|month)|monthly", t):
        kind = lead.pay_kind = "monthly"
    if kind == "monthly":
        lead.hours = 160; rate = pay / 160
    elif kind == "hourly":
        lead.hours = 20; rate = pay
    elif kind == "salary":
        lead.hours = 2080; rate = pay / 2080
    elif pay > 0:
        lead.hours = max(3.0, min(80.0, pay / 45)); rate = pay / lead.hours
        if kind == "bounty": lead.hours = max(lead.hours, 6); rate = pay / lead.hours
    else:
        lead.hours = 10; rate = 25.0  # unknown budget: assume low
    lead.usd_per_hour = round(rate, 1)
    # win probability
    p = 0.04 + 0.025 * fit
    if not lead.is_buyer: p *= 0.15
    age = lead.age_h()
    p *= 1.4 if age < 6 else 1.15 if age < 24 else 1.0 if age < 72 else 0.6 if age < 24 * 14 else 0.3
    c = lead.competition
    if c >= 0: p *= 1.3 if c <= 2 else 1.0 if c <= 10 else 0.7 if c <= 30 else 0.45 if c <= 80 else 0.25
    if "gated" in lead.flags: p *= 0.4
    if "off-stack" in lead.flags: p *= 0.2
    if "scam-risk" in lead.flags: p *= 0.05
    if "removed" in lead.flags: p *= 0.6
    if "needs-track-record" in lead.flags: p *= 0.6
    if "needs-approved-profile" in lead.flags: p *= 0.5   # Arc/Braintrust profile not approved yet
    if "ft-or-contract-role" in lead.flags: p *= 0.5      # multi-round hiring, slow to first $
    if "repo-unvetted" in lead.flags: p *= 0.3
    if "contest" in lead.flags: p *= 0.5
    if "middleman" in lead.flags: p *= 0.3
    if "local-only?" in lead.flags: p *= 0.5
    if kind == "salary": p *= 0.35  # FT hiring cycles are slow
    lead.p_win = round(min(p, 0.6), 3)
    lead.rank = round(lead.usd_per_hour * lead.p_win * (1 + fit / 10), 2)
    return lead


class Seen:
    """Seen-state that marks leads NEW vs SEEN but never hides them (old bug: dedupe list of 903
    URLs suppressed still-open leads). Keyed source:id with first-seen epoch; pruned after 30 days."""
    def __init__(self, path=os.path.join(STATE_DIR, "seen.json")):
        self.path = path
        try: self.d = json.load(open(path))
        except Exception: self.d = {}
        # import legacy reddit/HN dedupe lists once (read-only on old files)
        if not self.d.get("_legacy_imported"):
            for f, src in ((os.path.join(LEGACY_DIR, "leads_seen.txt"), None), (os.path.join(LEGACY_DIR, "hn_seen.txt"), "hn")):
                if os.path.exists(f):
                    for ln in open(f):
                        ln = ln.split("|")[0].strip()
                        if not ln or ln.startswith("#"): continue
                        m = re.search(r"/comments/([a-z0-9]+)", ln)
                        key = f"reddit:{m.group(1)}" if m else (f"hn:{ln}" if src == "hn" else f"url:{ln}")
                        self.d.setdefault(key, 0)
            self.d["_legacy_imported"] = 1

    def mark(self, lead):
        k = f"{lead.source.split('/')[0]}:{lead.id}"
        lead.new = k not in self.d
        if lead.new: self.d[k] = int(time.time())
        if lead.url in self.d or f"url:{lead.url}" in self.d: lead.new = False

    def save(self):
        cut = time.time() - 30 * 86400
        self.d = {k: v for k, v in self.d.items() if k.startswith("_") or v == 0 or v > cut}
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"; json.dump(self.d, open(tmp, "w")); os.replace(tmp, self.path)


def strip_html(s):
    s = re.sub(r"<br\s*/?>|</p>|</li>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    import html
    return re.sub(r"[ \t]+", " ", html.unescape(html.unescape(s))).strip()


def to_dict(lead): return asdict(lead)
