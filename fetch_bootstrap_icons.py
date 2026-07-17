#!/usr/bin/env python3
"""
fetch_bootstrap_icons.py
========================
Fetch EVERY Bootstrap Icon, convert each SVG to a base64 PNG, and save all of
them into a single text file.

This mirrors the exact pipeline used inside advanced-kpi-builder.html
(rbFetchIconTo + rbSvgToSlatePng):

  1. Download the SVG from   https://cdn.jsdelivr.net/npm/bootstrap-icons/icons/{name}.svg
  2. Normalise the SVG       - replace `currentColor` with the slate colour #334155
                             - if the <svg> tag has no fill attribute, add fill="#334155"
                             - strip any width/height and force width="96" height="96"
  3. Rasterise to a 96x96 PNG and base64-encode it (payload only, no data: prefix)
     -> identical to what the builder stores in ICONS[].b64 / rbIconCache

The list of icon names comes from the package's own metadata file:
  https://cdn.jsdelivr.net/npm/bootstrap-icons/font/bootstrap-icons.json
which maps every icon name to its font codepoint - i.e. the complete set.

Usage
-----
  pip install cairosvg            # the only non-stdlib dependency (SVG -> PNG)
  python fetch_bootstrap_icons.py                       # writes bootstrap-icons-b64.txt
  python fetch_bootstrap_icons.py --format json         # writes ICONS-compatible JSON
  python fetch_bootstrap_icons.py --limit 25            # quick test run
  python fetch_bootstrap_icons.py --size 96 --color "#334155" --workers 8

Output (txt format, default) - one icon per line:
  icon-name|<base64 png>

Output (json format) - ready to merge into the builder's ICONS array:
  [{"slug": "cart4", "label": "cart4", "kw": "cart4 bootstrap icon", "b64": "..."}, ...]
"""

import argparse
import base64
import concurrent.futures
import json
import re
import sys
import time
import urllib.error
import urllib.request

CDN_BASE   = "https://cdn.jsdelivr.net/npm/bootstrap-icons"
LIST_URL   = CDN_BASE + "/font/bootstrap-icons.json"
ICON_URL   = CDN_BASE + "/icons/{name}.svg"
USER_AGENT = "kpi-builder-icon-fetcher/1.0 (+https://icons.getbootstrap.com)"

try:
    import cairosvg  # SVG -> PNG rasteriser
except ImportError:
    sys.exit(
        "The 'cairosvg' package is required to rasterise SVGs to PNG.\n"
        "Install it with:\n\n    pip install cairosvg\n"
    )


# --------------------------------------------------------------------------
# HTTP helpers (stdlib only, small retry for transient CDN hiccups)
# --------------------------------------------------------------------------
def http_get(url, retries=2, timeout=30):
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("GET failed for %s: %s" % (url, last_err))


def list_all_icon_names():
    """The bootstrap-icons.json metadata file lists every icon name."""
    data = json.loads(http_get(LIST_URL).decode("utf-8"))
    return sorted(data.keys())


# --------------------------------------------------------------------------
# SVG normalisation - a 1:1 port of the builder's rbSvgToSlatePng preamble
# --------------------------------------------------------------------------
def normalise_svg(svg_text, color, size):
    s = svg_text

    # currentColor -> fixed colour (Bootstrap icons use currentColor throughout)
    if "currentColor" in s:
        s = s.replace("currentColor", color)
    # otherwise, if the <svg> tag itself carries no fill, inject one
    elif not re.search(r"<svg[^>]*\sfill=", s):
        s = re.sub(r"<svg ", '<svg fill="%s" ' % color, s, count=1)

    # strip width/height from the opening tag, then force our target size
    def fix_tag(m):
        tag = m.group(0)
        tag = re.sub(r'\swidth="[^"]*"', "", tag)
        tag = re.sub(r'\sheight="[^"]*"', "", tag)
        return tag.replace("<svg", '<svg width="%d" height="%d"' % (size, size), 1)

    s = re.sub(r"<svg[^>]*>", fix_tag, s, count=1)
    return s


def svg_to_png_b64(svg_text, color, size):
    """Normalise, rasterise at size x size, return the base64 PNG payload."""
    svg = normalise_svg(svg_text, color, size)
    png_bytes = cairosvg.svg2png(
        bytestring=svg.encode("utf-8"),
        output_width=size,
        output_height=size,
    )
    return base64.b64encode(png_bytes).decode("ascii")


# --------------------------------------------------------------------------
# Per-icon worker
# --------------------------------------------------------------------------
def fetch_one(name, color, size):
    raw = http_get(ICON_URL.format(name=name)).decode("utf-8")
    if "<svg" not in raw:
        raise RuntimeError("not-svg")
    return name, svg_to_png_b64(raw, color, size)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Fetch all Bootstrap icons as base64 PNGs into one text file.")
    ap.add_argument("--out",     default=None, help="output file (default: bootstrap-icons-b64.txt or .json)")
    ap.add_argument("--format",  default="txt", choices=["txt", "json"], help="txt = name|b64 lines, json = ICONS-style array")
    ap.add_argument("--color",   default="#334155", help="fill colour baked into the PNGs (builder default: slate #334155)")
    ap.add_argument("--size",    default=96, type=int, help="raster size in px (builder default: 96)")
    ap.add_argument("--workers", default=8, type=int, help="parallel downloads")
    ap.add_argument("--limit",   default=0, type=int, help="only fetch the first N icons (0 = all, useful for testing)")
    args = ap.parse_args()

    out_path = args.out or ("bootstrap-icons-b64.json" if args.format == "json" else "bootstrap-icons-b64.txt")

    print("Listing icons from %s ..." % LIST_URL)
    names = list_all_icon_names()
    if args.limit > 0:
        names = names[: args.limit]
    total = len(names)
    print("Fetching %d icons at %dx%d in %s using %d workers ..." % (total, args.size, args.size, args.color, args.workers))

    results, failures = {}, []
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_one, n, args.color, args.size): n for n in names}
        for fut in concurrent.futures.as_completed(futures):
            name = futures[fut]
            done += 1
            try:
                _, b64 = fut.result()
                results[name] = b64
            except Exception as e:
                failures.append((name, str(e)))
            if done % 100 == 0 or done == total:
                print("  %d / %d  (%d failed)" % (done, total, len(failures)))

    # single output file, icons in stable alphabetical order
    ordered = [(n, results[n]) for n in names if n in results]
    if args.format == "json":
        payload = [
            {"slug": n, "label": n, "kw": n + " bootstrap icon", "b64": b}
            for n, b in ordered
        ]
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
    else:
        with open(out_path, "w", encoding="utf-8") as f:
            for n, b in ordered:
                f.write("%s|%s\n" % (n, b))

    print("\nWrote %d icons to %s" % (len(ordered), out_path))
    if failures:
        print("%d icons failed:" % len(failures))
        for n, err in failures[:20]:
            print("  - %s: %s" % (n, err))
        if len(failures) > 20:
            print("  ... and %d more" % (len(failures) - 20))
        sys.exit(1)


if __name__ == "__main__":
    main()
