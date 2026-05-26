import argparse
import csv
import math
import os
import sys
import warnings

import requests
import urllib3
from tqdm import tqdm

import db
import scraper
import downloader

warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)


def _export_and_clear(conn, alias: str) -> None:
    cursor = conn.execute(
        "SELECT * FROM items WHERE collection = ? ORDER BY item_id", (alias,)
    )
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()

    if not rows:
        print(f"[{alias}] No rows to export.")
        return

    csv_path = f"{alias}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    conn.execute("DELETE FROM items WHERE collection = ?", (alias,))
    conn.commit()
    print(f"[{alias}] Exported {len(rows)} rows to {csv_path}, removed from DB.")


def crawl_collection(
    session: requests.Session,
    conn,
    alias: str,
    images_dir: str,
    delay: float,
    limit: int = 0,
    maxrecs: int = 100,
) -> None:
    alias = alias.upper()
    print(f"\n[{alias}] Fetching total item count...")

    _, total = scraper.search_collection(session, alias, page=1, delay=0)
    if total == 0:
        print(f"[{alias}] No items found. Check the collection alias.")
        return

    total_pages = math.ceil(total / 10)
    target = min(total, limit) if limit > 0 else total
    print(f"[{alias}] {total} items across {total_pages} pages, processing {target}.")

    processed = 0
    skipped = 0
    failed = 0

    with tqdm(total=target, unit="item", desc=alias) as bar:
        for page_num in range(1, total_pages + 1):
            items, _ = scraper.search_collection(
                session, alias, page=page_num, delay=delay
            )
            if not items:
                break

            for item in items:
                item_id = item.get("itemId") or item.get("pointer") or item.get("id")
                if item_id is None:
                    continue

                item_id = int(item_id)

                if db.item_exists(conn, alias, item_id):
                    skipped += 1
                    bar.update(1)
                    bar.set_postfix(skipped=skipped, failed=failed)
                    continue

                try:
                    detail = scraper.fetch_item(session, alias, item_id, delay=delay)
                except Exception as e:
                    tqdm.write(f"  [WARN] fetch_item({alias}/{item_id}) failed: {e}")
                    failed += 1
                    bar.update(1)
                    bar.set_postfix(skipped=skipped, failed=failed)
                    continue

                fields = detail.get("fields") or []
                metadata = {f["key"]: f.get("value") for f in fields}
                image_url = detail.get("imageUri")
                if image_url and image_url.startswith("/"):
                    image_url = "https://www.vads.ac.uk" + image_url

                image_path = downloader.download_image(
                    session, alias, item_id, images_dir, image_url
                )

                db.upsert_item(
                    conn,
                    alias,
                    item_id,
                    metadata,
                    image_url,
                    image_path,
                )
                processed += 1
                bar.update(1)
                bar.set_postfix(skipped=skipped, failed=failed)
                if limit > 0 and processed >= limit:
                    break

            if limit > 0 and processed >= limit:
                break

    print(
        f"[{alias}] Done. processed={processed}, skipped={skipped}, failed={failed}"
    )
    _export_and_clear(conn, alias)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl artwork collections from vads.ac.uk"
    )
    parser.add_argument(
        "collections",
        nargs="+",
        metavar="COLLECTION",
        help="One or more collection aliases (e.g. IWM PHOTOGRAPHIC)",
    )
    parser.add_argument("--db", default="ica.db", metavar="PATH", help="SQLite DB path (default: ica.db)")
    parser.add_argument("--images", default="images", metavar="DIR", help="Image output directory (default: images/)")
    parser.add_argument("--delay", type=float, default=0.3, metavar="SECS", help="Delay between requests in seconds (default: 0.3)")
    parser.add_argument("--limit", type=int, default=0, metavar="N", help="Max items to crawl per collection, 0 = no limit (default: 0)")
    args = parser.parse_args()

    conn = db.init_db(args.db)
    print(f"Database: {args.db}")
    print(f"Images:   {args.images}/")

    session = requests.Session()
    session.headers.update({"User-Agent": "vads-art-crawler/1.0"})

    for alias in args.collections:
        try:
            crawl_collection(session, conn, alias, args.images, args.delay, limit=args.limit)
        except KeyboardInterrupt:
            print("\nInterrupted. Progress saved — re-run to resume.")
            sys.exit(0)
        except Exception as e:
            print(f"[ERROR] Collection {alias}: {e}")

    conn.close()


if __name__ == "__main__":
    main()
