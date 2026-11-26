#!/usr/bin/env python3
"""Download every Project Gutenberg slice of the Encyclopaedia Britannica,
11th Edition (plain text, UTF-8) into ./eb11/ and write ./manifest.csv.

Safe to re-run: files that already exist are skipped.
"""
import csv
import io
import os
import sys
import time
import urllib.request

CATALOG = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv"
PREFIX = "encyclopaedia britannica, 11th edition"
OUT_DIR = "eb11"
MANIFEST = "manifest.csv"
USER_AGENT = "eb11-fetch/1.0 (personal offline-reader project)"
DELAY_SECONDS = 1.5


def get(url, tries=5):
    last_error = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - retry on anything
            last_error = exc
            time.sleep(3 * (attempt + 1))
    raise last_error


def find_slices():
    raw = get(CATALOG).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    found = []
    for row in reader:
        title = " ".join((row.get("Title") or "").split())
        if not title.lower().startswith(PREFIX):
            continue
        if (row.get("Type") or "") != "Text":
            continue
        if "en" not in (row.get("Language") or ""):
            continue
        found.append((int(row["Text#"]), title))
    found.sort()
    return found


def fetch_text(book_id):
    urls = [
        f"https://www.gutenberg.org/ebooks/{book_id}.txt.utf-8",
        f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt",
    ]
    for url in urls:
        try:
            data = get(url)
        except Exception:  # noqa: BLE001
            continue
        if len(data) > 1000:
            return data
    return None


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    slices = find_slices()
    print(f"Found {len(slices)} matching books in the catalog", flush=True)
    if not slices:
        print("No books found; the catalog format may have changed.")
        sys.exit(1)

    rows = []
    downloaded = skipped = failed = 0
    for book_id, title in slices:
        path = os.path.join(OUT_DIR, f"{book_id}.txt")
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            status = "skipped (already there)"
            skipped += 1
        else:
            data = fetch_text(book_id)
            if data is None:
                status = "FAILED"
                failed += 1
            else:
                with open(path, "wb") as fh:
                    fh.write(data)
                status = "ok"
                downloaded += 1
            time.sleep(DELAY_SECONDS)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        rows.append((book_id, title, size, status))
        print(f"{book_id}: {status} ({size} bytes) {title[:70]}", flush=True)

    with open(MANIFEST, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "title", "bytes", "status"])
        writer.writerows(rows)

    total = sum(r[2] for r in rows)
    print(
        f"\nDone. downloaded={downloaded} skipped={skipped} failed={failed} "
        f"total={total / 1_000_000:.1f} MB"
    )


if __name__ == "__main__":
    main()
