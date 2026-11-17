"""Download the SEC Financial Statement Data Sets (quarterly ZIPs) into a folder.

Run on your own computer (Anaconda Prompt):
    python download_sec_fsds.py "C:\\Users\\<you>\\quant-lab\\raw\\sec_fsds"

The SEC asks automated clients to identify themselves: put your own name and
e-mail in USER_AGENT below before running. The script waits between files to
stay well under the SEC's rate limit and skips files it already has.
"""

import sys
import time
import urllib.request
from pathlib import Path

USER_AGENT = "Your Name your.email@example.com"  # <-- fill in before running
BASE = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/{y}q{q}.zip"
FIRST = (2009, 2)
LAST = (2026, 3)


def quarters():
    y, q = FIRST
    while (y, q) <= LAST:
        yield y, q
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)


def main(dest: str) -> None:
    if "example.com" in USER_AGENT:
        sys.exit("Put your own name and e-mail in USER_AGENT first.")
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    for y, q in quarters():
        path = out / f"{y}q{q}.zip"
        if path.exists() and path.stat().st_size > 0:
            continue
        req = urllib.request.Request(BASE.format(y=y, q=q), headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as f:
                f.write(r.read())
            print(f"{path.name}: {path.stat().st_size / 1e6:.1f} MB")
        except Exception as e:  # a quarter not yet published, or a network error
            path.unlink(missing_ok=True)
            print(f"{y}q{q}: skipped ({e})")
        time.sleep(1.0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sec_fsds")
