#!/usr/bin/env python3
"""Download every Project Gutenberg slice of the Encyclopaedia Britannica,
11th Edition (plain text) into ./eb11/ as UTF-8 and write ./manifest.csv.

v2: tries several ways to get the list of books, downloads from the
Gutenberg mirror first, and prints every error it hits.
Safe to re-run: files that already exist are skipped.
"""
import csv
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

PREFIX = "encyclopaedia britannica, 11th edition"
OUT_DIR = "eb11"
MANIFEST = "manifest.csv"
USER_AGENT = "eb11-fetch/2.0 (personal offline-reader project)"
DELAY_SECONDS = 1.5
MIRROR = "https://aleph.gutenberg.org"

CATALOG_URL = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv"
GUTENDEX_URL = "https://gutendex.com/books/?search=encyclopaedia+britannica+11th+edition"
SEARCH_URL = (
    "https://www.gutenberg.org/ebooks/search/"
    "?query=Encyclopaedia+Britannica+11th+Edition&start_index={start}"
)


def get(url, tries=3):
    last_error = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - retry on anything
            last_error = exc
            time.sleep(2 * (attempt + 1))
    raise last_error


def clean(title):
    return " ".join((title or "").split())


def matches(title):
    return clean(title).lower().startswith(PREFIX)


# ---------- ways to get the list of books ----------

def from_catalog():
    raw = get(CATALOG_URL).decode("utf-8-sig")
    found = []
    for row in csv.DictReader(io.StringIO(raw)):
        title = clean(row.get("Title"))
        if matches(title) and (row.get("Type") or "") == "Text":
            if "en" in (row.get("Language") or ""):
                found.append((int(row["Text#"]), title))
    return found


def from_gutendex():
    found = []
    url = GUTENDEX_URL
    for _ in range(30):
        data = json.loads(get(url).decode("utf-8"))
        for book in data.get("results", []):
            if matches(book.get("title")):
                found.append((int(book["id"]), clean(book["title"])))
        url = data.get("next")
        if not url:
            break
        time.sleep(1)
    return found


def from_search_pages():
    found = {}
    pattern = re.compile(
        r'href="/ebooks/(\d+)".*?<span class="title">(.*?)</span>', re.S
    )
    for page in range(30):
        html = get(SEARCH_URL.format(start=1 + page * 25)).decode("utf-8", "replace")
        hits = pattern.findall(html)
        new = 0
        for book_id, title in hits:
            title = clean(re.sub(r"<[^>]+>", "", title))
            if matches(title) and int(book_id) not in found:
                found[int(book_id)] = title
                new += 1
        if not hits:
            break
        time.sleep(1)
    return list(found.items())


def find_slices():
    for name, func in (
        ("Gutenberg catalog", from_catalog),
        ("Gutendex", from_gutendex),
        ("Gutenberg search pages", from_search_pages),
    ):
        try:
            found = sorted(set(func()))
        except Exception as exc:  # noqa: BLE001
            print(f"[list] {name} failed: {exc}", flush=True)
            continue
        print(f"[list] {name}: {len(found)} books", flush=True)
        if found:
            return found
    return []


# ---------- downloading one book ----------

def mirror_urls(book_id):
    digits = str(book_id)
    folder = "/".join(digits[:-1]) + "/" + digits
    base = f"{MIRROR}/{folder}"
    return [
        (f"{base}/{book_id}-0.txt", "utf-8"),
        (f"{base}/{book_id}.txt", "utf-8"),
        (f"{base}/{book_id}-8.txt", "latin-1"),
    ]


def fetch_text(book_id):
    candidates = mirror_urls(book_id) + [
        (f"https://www.gutenberg.org/ebooks/{book_id}.txt.utf-8", "utf-8"),
        (f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt", "utf-8"),
    ]
    for url, encoding in candidates:
        try:
            data = get(url, tries=2)
        except Exception as exc:  # noqa: BLE001
            print(f"    {url} -> {exc}", flush=True)
            continue
        if len(data) > 1000:
            if encoding != "utf-8":
                data = data.decode(encoding).encode("utf-8")
            return data
    return None


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    slices = find_slices()
    print(f"Found {len(slices)} matching books", flush=True)
    if not slices:
        print("No books found from any source.")
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
    if downloaded + skipped == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
