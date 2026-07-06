"""Print the fetched feed as JSON lines - lets an offline session generate a
digest from live data by reading the workflow log.

Usage (GitHub Actions or any networked host):  python dump_feed.py
"""

import json

from fedwatch import sources
from fedwatch.classify import DEFAULT_WATCHLIST


def main() -> int:
    items, errors, used_sample = sources.fetch_all(days_back=14,
                                                   watchlist=DEFAULT_WATCHLIST)
    print(f"###FEED_START### sample={used_sample} errors={len(errors)} items={len(items)}")
    for it in items:
        row = dict(it)
        row["summary"] = (row.get("summary") or "")[:350]
        print("ITEM " + json.dumps(row, ensure_ascii=False))
    print("###FEED_END###")
    for e in errors:
        print("ERR " + e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
