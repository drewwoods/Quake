#!/usr/bin/env python3
"""Check the external citations in the architecture guides.

Deliberately separate from build.py: building must not need the network, but
citations rot, so this is run by hand or in CI.

    python3 docs/architecture/check-links.py            # check every guide
    python3 docs/architecture/check-links.py --slow 2   # gentler on old hosts
    python3 docs/architecture/check-links.py design-history

Reports each URL's status, and for anything that fails, the closest Wayback
snapshot so the citation can be repaired rather than dropped. Exit status is 1
if any URL failed, so CI can gate on it.

Note that a 403 is usually bot-blocking, not rot — bluesnews.com refuses
scripted requests but serves browsers fine. Those are reported separately from
genuine failures and do not fail the run.
"""

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

# A real browser UA. Several of the older hosts reject the Python default.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"

URL = re.compile(r"https?://[^\s)\"'<>]+")
TRAILING = ".,;:"

WAYBACK = "https://archive.org/wayback/available?url="

# Hosts that block scripted requests but are fine in a browser. A failure from
# one of these is reported but not counted against the run.
BOT_BLOCKED = ("bluesnews.com",)


def cited_urls(guides):
    """Every external URL cited in the given guides' section sources."""
    found = {}
    for guide in guides:
        pattern = os.path.join(HERE, guide, "sections", "*.md")
        import glob
        for path in sorted(glob.glob(pattern)):
            text = open(path, encoding="utf-8").read()
            for m in URL.finditer(text):
                url = m.group(0).rstrip(TRAILING)
                found.setdefault(url, []).append(os.path.basename(path))
    return found


def fetch_status(url, timeout=30):
    """Return an HTTP status, or a transport error string."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:                      # DNS, TLS, timeout, redirect loop
        return type(e).__name__


def wayback(url, timeout=30):
    """Closest Wayback snapshot URL, or None."""
    req = urllib.request.Request(WAYBACK + urllib.parse.quote(url, safe=""),
                                 headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            snap = json.load(r).get("archived_snapshots", {}).get("closest")
    except Exception:
        return None
    return snap["url"].replace("http://", "https://") if snap else None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("guides", nargs="*", default=None,
                    help="guide directories to check (default: all)")
    ap.add_argument("--slow", type=float, default=0, metavar="SECONDS",
                    help="serialise requests, pausing between them")
    args = ap.parse_args()

    guides = args.guides or [d for d in sorted(os.listdir(HERE))
                             if os.path.isdir(os.path.join(HERE, d, "sections"))]
    urls = cited_urls(guides)
    if not urls:
        print("no citations found in: %s" % ", ".join(guides))
        return 0

    print("checking %d citations across %s\n" % (len(urls), ", ".join(guides)))

    results = {}
    if args.slow:
        for u in sorted(urls):
            results[u] = fetch_status(u)
            time.sleep(args.slow)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for u, status in zip(sorted(urls), pool.map(fetch_status, sorted(urls))):
                results[u] = status

    ok, blocked, bad = [], [], []
    for u in sorted(results):
        s = results[u]
        if s == 200:
            ok.append(u)
        elif any(h in u for h in BOT_BLOCKED):
            blocked.append((u, s))
        else:
            bad.append((u, s))

    for u in ok:
        print("  200  %s" % u)
    for u, s in blocked:
        print("  %-4s %s  (host blocks scripted requests; check in a browser)" % (s, u))

    if bad:
        print("\n%d citation(s) failed:\n" % len(bad))
        for u, s in bad:
            print("  %-4s %s" % (s, u))
            print("       cited in: %s" % ", ".join(sorted(set(urls[u]))))
            snap = wayback(u)
            print("       archived: %s" % (snap or "no Wayback snapshot"))
        return 1

    print("\nall citations reachable (%d ok, %d bot-blocked)" % (len(ok), len(blocked)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
