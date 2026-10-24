"""python3 -m scan --all | --source reddit,hn [--hours 72] [--top 25] [--json] [--no-save]
Writes out/leads-<ts>.md + out/latest.json; exit 0 if >=1 source succeeded, 1 if all failed."""
import argparse, importlib, json, os, sys, time, traceback
from datetime import datetime
from .core import score, Seen, LOG, STATS, OUT_DIR, PT, to_dict

ALL = ["reddit", "craigslist", "hn", "algora", "expensify", "freelancer", "superteam", "mercor", "braintrust",
       "arc", "remoteboards", "linkedin", "x"]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scan")
    ap.add_argument("--all", action="store_true"); ap.add_argument("--source", default="")
    ap.add_argument("--hours", type=int, default=72); ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--json", action="store_true"); ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--new-only", action="store_true", help="print only leads not seen in earlier runs")
    a = ap.parse_args(argv)
    names = ALL if a.all or not a.source else [s.strip() for s in a.source.split(",")]
    leads, failed = [], []
    for n in names:
        t0 = time.time()
        try:
            got = importlib.import_module(f".sources.{n}", __package__).scan(hours=a.hours)
            leads += got
        except Exception as e:  # never swallow: record + continue with other sources
            failed.append(n); LOG.append((n, "error", f"{type(e).__name__}: {e}"))
            STATS.append({"source": n, "http": "FAILED", "error": str(e)[:200], "ms": int((time.time() - t0) * 1000)})
            traceback.print_exc(file=sys.stderr)
    seen = Seen()
    for l in leads: score(l); seen.mark(l)
    if not a.no_save: seen.save()
    keep = [l for l in leads if "scam-risk" not in l.flags]
    keep.sort(key=lambda l: -l.rank)
    if a.new_only: keep = [l for l in keep if l.new]
    stamp = datetime.now(PT).strftime("%Y-%m-%d_%H%M")
    os.makedirs(OUT_DIR, exist_ok=True)
    rep = {"run_pt": datetime.now(PT).strftime("%a %b %d %Y %-I:%M %p PT"), "sources": names, "failed": failed,
           "stats": STATS, "log": LOG[-60:], "leads": [to_dict(l) | {"posted_pt": l.posted_pt()} for l in keep]}
    json.dump(rep, open(os.path.join(OUT_DIR, "latest.json"), "w"), indent=1)
    md = [f"# Lead scan {rep['run_pt']}", "", "| # | rank | $/h | p(win) | pay as shown | posted | source | title | flags | url |", "|---|---|---|---|---|---|---|---|---|---|"]
    for i, l in enumerate(keep[: max(a.top, 50)], 1):
        md.append(f"| {i} | {l.rank} | {l.usd_per_hour} | {l.p_win} | {l.pay_text or 'not stated'} | {l.posted_pt()} | {l.source} | "
                  f"{('NEW ' if l.new else '') + l.title[:80].replace('|', '/')} | {','.join(l.flags)} | {l.url} |")
    md += ["", "## Source stats", *[f"- {json.dumps(s)}" for s in STATS]]
    open(os.path.join(OUT_DIR, f"leads-{stamp}.md"), "w").write("\n".join(md))
    if a.json: print(json.dumps(rep, indent=1)); 
    else:
        for s in STATS: print(json.dumps(s))
        for i, l in enumerate(keep[: a.top], 1):
            print(f"{i:>2}. [{l.rank:>6}] ${l.usd_per_hour}/h p={l.p_win} {l.source} | {l.title[:70]} | {l.pay_text or 'pay n/s'} | "
                  f"{l.posted_pt()} | {','.join(l.flags)} | {l.url}{' NEW' if l.new else ''}")
        print(f"report: {os.path.join(OUT_DIR, f'leads-{stamp}.md')}")
    return 1 if failed and len(failed) == len(names) else 0


if __name__ == "__main__": sys.exit(main())
