#!/usr/bin/env python3
"""Download the Internet Archive OCR text of the Encyclopaedia Britannica,
11th Edition, for the volumes Project Gutenberg does NOT have:
volume 1 and volumes 18-28 (Medal ... Zymotic diseases).

Saves ./eb11_ia/volNN.txt (UTF-8) and writes ./manifest_ia.csv.
Safe to re-run: volumes that are already downloaded are skipped.
"""
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

OUT_DIR = "eb11_ia"
MANIFEST = "manifest_ia.csv"
VOLUMES = [1] + list(range(18, 29))
USER_AGENT = "eb11-fetch-ia/1.0 (personal offline-reader project)"
MIN_BYTES = 2_000_000  # a real volume is several MB; smaller means something is wrong
DELAY_SECONDS = 3

SEARCH_URL = (
    "https://archive.org/advancedsearch.php?q=identifier%3A%28encyclopaediabri*chisrich%29"
    "&fl%5B%5D=identifier&rows=200&output=json"
)


def get(url, tries=4, timeout=300):
    last_error = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                raise
            last_error = exc
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(5 * (attempt + 1))
    raise last_error


def to_roman(n):
    out = ""
    for value, symbol in ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out += symbol
            n -= value
    return out


def find_identifiers():
    """Map volume number -> Internet Archive identifier."""
    found = {}
    try:
        data = json.loads(get(SEARCH_URL, tries=3, timeout=120).decode("utf-8"))
        for doc in data.get("response", {}).get("docs", []):
            ident = doc.get("identifier", "")
            m = re.fullmatch(r"encyclopaediabri(\d+)chisrich", ident)
            if m:
                found[int(m.group(1))] = ident
        print(f"[ids] archive.org search found volumes: {sorted(found)}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[ids] archive.org search failed ({exc}); using name pattern", flush=True)
    for n in VOLUMES:
        found.setdefault(n, f"encyclopaediabri{n:02d}chisrich")
    return found


def fetch_volume_text(ident):
    direct = f"https://archive.org/download/{ident}/{ident}_djvu.txt"
    try:
        return get(direct)
    except urllib.error.HTTPError as exc:
        if exc.code not in (404, 410):
            raise
        print(f"    {direct} -> {exc}; looking in the item's file list", flush=True)
    meta = json.loads(get(f"https://archive.org/metadata/{ident}", tries=3).decode("utf-8"))
    names = [f["name"] for f in meta.get("files", []) if f.get("name", "").endswith("_djvu.txt")]
    if not names:
        names = [f["name"] for f in meta.get("files", []) if f.get("name", "").endswith(".txt")]
    if not names:
        raise RuntimeError("no text file in this item")
    return get(f"https://archive.org/download/{ident}/{urllib.parse.quote(names[0])}")


def check_volume(data, n):
    head = data[:30000].decode("utf-8", "replace")
    m = re.search(r"VOLUME\s+([IVXL]+)\b", head)
    if "ELEVENTH EDITION" not in head.upper():
        return "CHECK (no 'ELEVENTH EDITION' near the start)"
    if m and m.group(1) != to_roman(n):
        return f"CHECK (header says volume {m.group(1)}, expected {to_roman(n)})"
    return "ok"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    idents = find_identifiers()
    rows = []
    downloaded = skipped = failed = 0
    for n in VOLUMES:
        ident = idents[n]
        path = os.path.join(OUT_DIR, f"vol{n:02d}.txt")
        if os.path.exists(path) and os.path.getsize(path) >= MIN_BYTES:
            status = "skipped (already there)"
            skipped += 1
        else:
            try:
                data = fetch_volume_text(ident)
                text = data.decode("utf-8", "replace").encode("utf-8")
                if len(text) < MIN_BYTES:
                    status = f"FAILED (only {len(text)} bytes)"
                    failed += 1
                else:
                    status = check_volume(text, n)
                    with open(path, "wb") as fh:
                        fh.write(text)
                    downloaded += 1
            except Exception as exc:  # noqa: BLE001
                status = f"FAILED ({exc})"
                failed += 1
            time.sleep(DELAY_SECONDS)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        rows.append((n, ident, size, status))
        print(f"volume {n:2d}: {status} ({size} bytes) {ident}", flush=True)

    with open(MANIFEST, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["volume", "identifier", "bytes", "status"])
        writer.writerows(rows)

    total = sum(r[2] for r in rows)
    print(f"\nDone. downloaded={downloaded} skipped={skipped} failed={failed} "
          f"total={total / 1_000_000:.1f} MB")
    if downloaded + skipped == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
