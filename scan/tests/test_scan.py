"""Smoke + regression harness. Offline (fixtures) always; live network hits when SCAN_LIVE=1.
Run: python3 -m unittest scan.tests.test_scan -v      (offline)
     SCAN_LIVE=1 python3 -m unittest scan.tests.test_scan -v                    (offline + live)"""
import json, os, re, time, threading, tempfile, unittest, http.server
from unittest import mock
from scan import core
from scan.core import Lead, score, parse_pay, get, FetchError, Seen
from scan.sources import reddit, craigslist, hn, freelancer, superteam, mercor, braintrust, arc, remoteboards, linkedin, x

FX = os.path.join(os.path.dirname(__file__), "fixtures")
LIVE = os.environ.get("SCAN_LIVE") == "1"
HAVE_FX = os.path.isdir(FX) and any(not f.startswith(".") for f in os.listdir(FX))
rd = lambda f: open(os.path.join(FX, f), encoding="utf-8").read()
js = lambda f: json.loads(rd(f))


def fake_get(mapping):
    """Patch core.get inside a source module: route URL substrings to fixture payloads."""
    def g(url, **kw):
        for k, v in mapping.items():
            if k in url:
                if isinstance(v, Exception): raise v
                return json.loads(v) if kw.get("expect") == "json" else v
        raise FetchError(404, url, "no fixture")
    return g


class Core(unittest.TestCase):
    def test_pay_parse(self):
        self.assertEqual(parse_pay("Budget $300 for 100k rows")[:2], (300.0, "fixed"))
        self.assertEqual(parse_pay("$40-60/hr remote")[:2], (60.0, "hourly"))
        self.assertEqual(parse_pay("$120k - $150k salary")[:2], (150000.0, "salary"))
        self.assertEqual(parse_pay("no money here")[0], 0.0)
        self.assertEqual(parse_pay("$0")[0], 0.0)

    def test_score_ranks_fit_buyer_over_offstack(self):
        now = time.time()
        a = score(Lead("reddit/forhire", "a", "u", "[Hiring] Python scraper for Shopify data, $400", now - 3600, competition=1))
        b = score(Lead("reddit/forhire", "b", "u", "[Hiring] Video editor for UGC, $400", now - 3600, competition=1))
        c = score(Lead("reddit/forhire", "c", "u", "[Hiring] Python bot, pay upfront fee to start", now - 3600))
        self.assertGreater(a.rank, b.rank); self.assertIn("off-stack", b.flags); self.assertIn("scam-risk", c.flags)

    def test_middleman_and_monthly(self):  # regression: referral farms + "$10,000/month" ranked #1
        l = score(Lead("reddit/PythonJobs", "m", "u", "[Hiring] Python devs", time.time(), body="DM me, I'll send the direct sign-up link. Leave a DM Sent comment"))
        self.assertIn("middleman", l.flags)
        m = score(Lead("reddit/hiring", "n", "u", "[HIRING] Software engineer", time.time(), body="Pay: $10,000 per month"))
        self.assertEqual(m.pay_kind, "monthly"); self.assertLess(m.usd_per_hour, 70)

    def test_known_scam_author(self):
        with mock.patch.object(core, "SCAMS", {"example_blocked_user"}):
            self.assertIn("scam-risk", score(Lead("x", "1", "u", "python bot", 0, author="example_blocked_user")).flags)

    @unittest.skipUnless(HAVE_FX, "third-party page fixtures are not redistributed; drop your own captures in tests/fixtures/")
    def test_block_page_rejected_as_json(self):  # regression: 403 HTML saved as forhire.json
        page = rd("reddit_block_page.html")
        with mock.patch("urllib.request.urlopen") as uo:
            r = mock.MagicMock(); r.__enter__.return_value = r; r.read.return_value = page.encode(); r.headers = {}
            uo.return_value = r
            with self.assertRaises(FetchError): get("http://x/new.json", expect="json", tries=1)

    def test_retry_on_429_then_ok(self):  # 403/429/422 path is logged and retried
        hits = []
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(s):
                hits.append(1)
                if len(hits) == 1: s.send_response(429); s.send_header("retry-after", "1"); s.end_headers(); return
                s.send_response(200); s.end_headers(); s.wfile.write(b'{"ok":1}')
            def log_message(*a): pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.assertEqual(get(f"http://127.0.0.1:{srv.server_port}/", expect="json"), {"ok": 1})
        self.assertEqual(len(hits), 2); self.assertTrue(any(l[1] == "retry" for l in core.LOG)); srv.shutdown()

    def test_seen_marks_but_never_hides_and_is_atomic(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "seen.json")
        s = Seen(p); s.d["_legacy_imported"] = 1
        l1 = Lead("reddit/x", "abc", "u1", "t", 0); s.mark(l1); s.save()
        s2 = Seen(p); l2 = Lead("reddit/x", "abc", "u1", "t", 0); s2.mark(l2)
        self.assertTrue(l1.new); self.assertFalse(l2.new)          # second run: 0 new on same data
        self.assertFalse(os.path.exists(p + ".tmp")); json.load(open(p))  # atomic write, valid JSON


class Reddit(unittest.TestCase):
    def test_classifier(self):
        self.assertTrue(reddit.classify("forhire", "Hiring", "[Hiring] Need a Python scraper", ""))
        self.assertFalse(reddit.classify("forhire", "For Hire", "[For Hire] Python dev", ""))
        self.assertFalse(reddit.classify("slavelabour", "Task", "\u2060[Offer] Landing pages", ""))  # zero-width char regression
        self.assertFalse(reddit.classify("PythonJobs", "", "[ForHire] [Remote] Custom Python scrapers", ""))
        self.assertFalse(reddit.classify("PythonJobs", "", "[Available] Senior Backend Engineer (Python)", ""))
        self.assertTrue(reddit.classify("webscraping", "", "Need data scraped", "I will pay $300 for this"))
        self.assertFalse(reddit.classify("SaaS", "", "I built a tool with a $0 budget", "my budget was $0"))
        self.assertFalse(reddit.classify("smallbusiness", "", "Make me Rich", "which would you personally be willing to pay for: a scraper"))

    @unittest.skipUnless(HAVE_FX, "third-party page fixtures are not redistributed; drop your own captures in tests/fixtures/")
    def test_removed_bodies_do_not_drop_hiring_posts(self):  # root cause #1 regression
        rows = js("arctic_forhire.json")["data"]
        hiring = [p for p in rows if reddit.classify("forhire", p.get("link_flair_text"), p["title"], p.get("selftext") or "")]
        removed = [p for p in hiring if p.get("selftext") == "[removed]"]
        self.assertGreater(len(hiring), 0)
        leads = [reddit.to_lead(p, {}) for p in removed]
        self.assertTrue(all("removed" in l.flags for l in leads))

    @unittest.skipUnless(HAVE_FX, "third-party page fixtures are not redistributed; drop your own captures in tests/fixtures/")
    def test_atom_parse(self):
        rows = reddit.parse_atom(rd("reddit_forhire.rss"))
        self.assertGreaterEqual(len(rows), 20); self.assertTrue(all(r["id"] and r["published"] for r in rows))

    def test_field_list_valid(self):  # 'permalink' -> HTTP 400 regression
        self.assertNotIn("permalink", reddit.FIELDS)

    @unittest.skipUnless(LIVE, "live")
    def test_live_arctic(self):
        rows = reddit.arctic("posts", "forhire", int(time.time()) - 24 * 3600)
        self.assertGreater(len(rows), 0)
        self.assertLess(time.time() - max(r["created_utc"] for r in rows), 6 * 3600)  # API not stale


class Craigslist(unittest.TestCase):
    @unittest.skipUnless(HAVE_FX, "third-party page fixtures are not redistributed; drop your own captures in tests/fixtures/")
    def test_list_and_view(self):
        rows = craigslist.parse_list(rd("cl_seattle_cpg.html"))
        self.assertGreater(len(rows), 10); self.assertTrue(all("/view/d/" in r["url"] for r in rows))
        ts, body, comp = craigslist.parse_view(rd("cl_view.html"))
        self.assertGreater(ts, 1.7e9); self.assertTrue(body); self.assertNotIn("<", comp); self.assertLess(len(comp), 81)

    def test_spam(self):
        self.assertTrue(craigslist.SPAM.search("Explore a flexible travel business you can build from home"))
        self.assertTrue(craigslist.SPAM.search("Python Development Skills and Career Training"))

    @unittest.skipUnless(LIVE, "live")
    def test_live(self):
        self.assertGreater(len(craigslist.parse_list(get("https://seattle.craigslist.org/search/cpg"))), 0)


class HN(unittest.TestCase):
    @unittest.skipUnless(HAVE_FX, "third-party page fixtures are not redistributed; drop your own captures in tests/fixtures/")
    def test_parse_freelancer_thread(self):
        with mock.patch.object(hn, "get", fake_get({"search_by_date": json.dumps({"hits": [
                {"title": "Ask HN: Freelancer? Seeking freelancer? (October 2026)", "objectID": "49922572", "created_at_i": 1}]}),
                "items/49922572": rd("hn_freelancer.json")})):
            leads = hn.scan()
        self.assertTrue(all(re.match(r"\s*SEEKING FREELANCER", l.body, re.I) for l in leads))  # sellers excluded

    @unittest.skipUnless(LIVE, "live")
    def test_live_threads(self):
        th = hn.threads(); self.assertIn("hiring", th); self.assertIn("freelancer", th)


class Platforms(unittest.TestCase):
    def run_src(self, mod, mapping):
        with mock.patch.object(mod, "get", fake_get(mapping)):
            return mod.scan(hours=24 * 365)

    @unittest.skipUnless(HAVE_FX, "third-party page fixtures are not redistributed; drop your own captures in tests/fixtures/")
    def test_freelancer(self):
        L = self.run_src(freelancer, {"projects/active": rd("freelancer.json")})
        self.assertTrue(all(l.competition <= freelancer.MAX_BIDS for l in L))
        self.assertTrue(all(l.pay_usd >= 15 for l in L))

    @unittest.skipUnless(HAVE_FX, "third-party page fixtures are not redistributed; drop your own captures in tests/fixtures/")
    def test_superteam(self):
        L = self.run_src(superteam, {"listings": rd("superteam.json")})
        self.assertTrue(all(l.url.startswith("https://earn.superteam.fun/listing/") for l in L))

    @unittest.skipUnless(HAVE_FX, "third-party page fixtures are not redistributed; drop your own captures in tests/fixtures/")
    def test_mercor(self):
        L = self.run_src(mercor, {"listings-explore-page": rd("mercor.json")})
        self.assertTrue(all(not mercor.BAD.search(l.title) for l in L))
        self.assertTrue(all(l.pay_kind != "hourly" or l.pay_usd >= 40 for l in L))

    @unittest.skipUnless(HAVE_FX, "third-party page fixtures are not redistributed; drop your own captures in tests/fixtures/")
    def test_braintrust(self):
        d = js("braintrust.json"); d["next"] = None
        L = self.run_src(braintrust, {"api/jobs": json.dumps(d)})
        self.assertGreaterEqual(len(d["results"]), 1); self.assertTrue(all("braintrust" in l.url for l in L))

    @unittest.skipUnless(HAVE_FX, "third-party page fixtures are not redistributed; drop your own captures in tests/fixtures/")
    def test_arc(self):
        jobs = arc.parse(rd("arc_python.html")); self.assertGreater(len(jobs), 5)

    @unittest.skipUnless(HAVE_FX, "third-party page fixtures are not redistributed; drop your own captures in tests/fixtures/")
    def test_remoteboards(self):
        L = self.run_src(remoteboards, {"remoteok.com/api": rd("remoteok.json"), "weworkremotely": rd("wwr.rss")})
        self.assertIsInstance(L, list)

    @unittest.skipUnless(HAVE_FX, "third-party page fixtures are not redistributed; drop your own captures in tests/fixtures/")
    def test_linkedin(self):
        rows = linkedin.parse(rd("linkedin.html")); self.assertGreater(len(rows), 5)
        self.assertTrue(all(r["url"].startswith("https://www.linkedin.com/jobs/view/") for r in rows))

    def test_x_inbox_filters(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "x.json")
        json.dump([{"id": "1", "text": "will pay $300 for a python scraper", "username": "a", "created_at": "2026-10-24T14:00:00Z",
                    "author_created_at": "2020-01-01T00:00:00Z"},
                   {"id": "2", "text": "RT @foo will pay", "username": "b"},
                   {"id": "3", "text": "need a bot", "username": "c", "author_created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}], open(p, "w"))
        with mock.patch.object(x, "INBOX", p):
            L = x.scan()
        self.assertEqual([l.id for l in L], ["1"])

    @unittest.skipUnless(LIVE, "live")
    def test_live_endpoints(self):
        for u in ["https://www.freelancer.com/api/projects/0.1/projects/active/?jobs[]=13&limit=1",
                  "https://earn.superteam.fun/api/listings?take=1", "https://aws.api.mercor.com/work/listings-explore-page",
                  "https://app.usebraintrust.com/api/jobs/?page_size=1", "https://remoteok.com/api",
                  "https://hn.algolia.com/api/v1/items/49922572"]:
            with self.subTest(u=u): self.assertTrue(get(u, expect="json"))
        self.assertTrue(arc.parse(get("https://arc.dev/remote-jobs/python")))
        self.assertTrue(get("https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss", expect="xml"))


if __name__ == "__main__": unittest.main()
