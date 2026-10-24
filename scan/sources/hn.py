"""Hacker News: auto-discovered 'Who is hiring?' + 'Freelancer? Seeking freelancer?' threads via Algolia.
Bugs fixed: the Freelancer thread (Oct = 49922572) was never scanned; thread IDs were hard-coded;
hn_seen.txt marked a comment seen forever even when it was re-edited; Who's-hiring full-time roles were
ranked like gigs."""
import re, time
from ..core import get, Lead, log, FetchError, STATS, strip_html

NAME = "hn"
ALG = "https://hn.algolia.com/api/v1"
FIT = re.compile(r"python|scrap|automation|\bbot|\bai\b|llm|rag\b|agent|full[- ]?stack|typescript|react|node|django|fastapi", re.I)
GIG = re.compile(r"contract|freelanc|part[- ]?time|consult|hourly|project[- ]based|\$\d+\s?/\s?h", re.I)


def threads():
    d = get(f"{ALG}/search_by_date?tags=story,author_whoishiring&hitsPerPage=12&attributesToRetrieve=title,objectID,created_at_i", expect="json")
    out = {}
    for h in d["hits"]:
        t = h["title"]
        kind = "freelancer" if "Freelancer?" in t else "hiring" if "Who is hiring" in t else None
        if kind and kind not in out: out[kind] = (h["objectID"], t, h["created_at_i"])
    out.setdefault("freelancer", ("49922572", "Ask HN: Freelancer? Seeking freelancer? (October 2026)", 0))
    return out


def comments(story):
    return get(f"{ALG}/items/{story}", expect="json", timeout=20).get("children") or []


def scan(hours=72, live=True):
    t0 = time.time(); leads = []; th = threads(); n_raw = 0
    for kind, (sid, title, ts) in th.items():
        try: kids = comments(sid)
        except FetchError as e: log(NAME, "warn", f"{sid}: {e}"); continue
        n_raw += len(kids)
        for c in kids:
            txt = strip_html(c.get("text") or "")
            if not txt: continue
            if kind == "freelancer":
                if not re.match(r"\s*SEEKING FREELANCER", txt, re.I): continue
            else:
                if not (re.search(r"remote", txt, re.I) and GIG.search(txt[:600]) and FIT.search(txt)): continue
            first = txt.split("\n")[0][:110]
            apply = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+|https?://\S+", txt)[:2]
            leads.append(Lead(f"{NAME}/{kind}", str(c["id"]), f"https://news.ycombinator.com/item?id={c['id']}", first,
                              c.get("created_at_i", 0), body=txt[:3000], author=c.get("author", ""),
                              is_buyer=True, tags=[title] + apply, flags=[] if kind == "freelancer" else ["ft-or-contract-role"]))
    # 3 extra in-thread searches (catch replies/edits that are not top-level)
    hid = th.get("hiring", (None,))[0]
    if hid:
        for q in ("contract", "freelance", "python remote"):
            try:
                d = get(f"{ALG}/search?tags=comment,story_{hid}&query={q.replace(' ', '%20')}&hitsPerPage=50", expect="json")
                for h in d["hits"]:
                    if h.get("parent_id") == int(hid): continue  # top-level already handled
                    txt = strip_html(h.get("comment_text") or "")
                    if GIG.search(txt) and FIT.search(txt) and re.search(r"remote", txt, re.I) and len(txt) > 200:
                        leads.append(Lead(f"{NAME}/hiring-reply", h["objectID"], f"https://news.ycombinator.com/item?id={h['objectID']}",
                                          txt[:110], h.get("created_at_i", 0), body=txt[:3000], author=h.get("author", ""),
                                          flags=["ft-or-contract-role"]))
            except FetchError as e: log(NAME, "warn", f"search {q}: {e}")
    seen = set(); uniq = [l for l in leads if not (l.id in seen or seen.add(l.id))]
    STATS.append({"source": NAME, "http": "ok", "threads": {k: v[0] for k, v in th.items()}, "n_raw": n_raw,
                  "n_fit": len(uniq), "ms": int((time.time() - t0) * 1000)})
    return uniq
