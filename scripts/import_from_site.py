#!/usr/bin/env python3
"""Import the public animadex.net catalogue into this local AnimaDex.

Given an export token (generate one at animadex.net -> Account -> "Offline
dataset export"), this:

  1. asks the site for a small manifest (catalogue version + R2 URLs);
  2. downloads characters.csv / artists.csv;
  3. downloads the WebP thumbnails (and, with --with-images, the full-res
     PNGs) straight from public R2 into this install's data folders;
  4. bulk-ingests the CSVs into the local SQLite DB.

Full vs delta is automatic: the first run does a full import; later runs
diff the catalogue's per-row versions against a saved state file and
fetch only what changed. A *full* pull is rate-limited to once / 48h on
the server side; if you're inside that window the script transparently
falls back to a delta.

Usually you'll run the wizard (import.bat / import.sh) rather than this
directly, but every option is exposed here too:

    python scripts/import_from_site.py --token YOUR_TOKEN
    python scripts/import_from_site.py --token YOUR_TOKEN --with-images
    python scripts/import_from_site.py --token YOUR_TOKEN --full --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote


def _enc(name):
    """URL-encode a filename the same way the site does (spaces -> %20,
    parentheses kept literal -- matches settings.r2_url, safe='/()')."""
    return quote(name, safe='()')

# Make `animadex` importable when run as a loose script (scripts/ is not
# on the package path).
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from animadex.config import load as load_config, ensure_dirs   # noqa: E402
from animadex.db import sanitize_filename                      # noqa: E402

DEFAULT_SITE = "https://animadex.net"
STATE_NAME   = ".animadex_import_state.json"
USER_AGENT   = "animadex-import/1"


# ---- tiny HTTP helpers ---------------------------------------------------

def _get(url, headers=None, timeout=60):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT,
                                               **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def get_json(url, headers=None):
    status, body = _get(url, headers)
    return status, json.loads(body.decode('utf-8'))


def download(url, dest: Path):
    """Download to a temp file then atomically rename. Returns bytes."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + '.part')
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, 'wb') as f:
        data = r.read()
        f.write(data)
    os.replace(tmp, dest)
    return len(data)


# ---- manifest ------------------------------------------------------------

def fetch_manifest(site, token, want_full):
    """Return (manifest_dict, did_full). Handles the 48h lock by falling
    back to a delta when a full pull is requested but locked."""
    base = site.rstrip('/') + '/api/export/manifest'
    url  = base + ('?full=1' if want_full else '')
    headers = {'X-Export-Token': token}
    try:
        status, data = get_json(url, headers)
    except urllib.error.HTTPError as e:
        if e.code == 429 and want_full:
            info = json.loads(e.read().decode('utf-8') or '{}')
            hrs = round((info.get('retry_after_secs') or 0) / 3600, 1)
            print(f"  ! Full download is locked for ~{hrs}h "
                  f"(once every 48h). Falling back to a delta update.")
            status, data = get_json(base, headers)   # delta
            return data, False
        if e.code == 401:
            sys.exit("Token rejected. Generate a fresh one at "
                     f"{site}/account and try again.")
        if e.code == 503:
            sys.exit("The site hasn't published the catalogue export yet. "
                     "Try again later.")
        raise
    return data, want_full


# ---- planning ------------------------------------------------------------

def _load_state(path: Path):
    if path.is_file():
        try:
            return json.loads(path.read_text('utf-8'))
        except (ValueError, OSError):
            pass
    return {'version': None, 'chars': {}, 'artists': {}, 'copyrights': {}}


def _read_csv(path: Path):
    import csv
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def plan_files(rows, key_col, prefixes, idx, state, cfg, full, with_images):
    """Yield (url, dest) download jobs for one mode, and return the
    new per-slug version map for the state file."""
    if key_col == 'character':
        thumb_pref, img_pref = prefixes['char_thumb'], prefixes['char_img']
        thumb_dir = Path(cfg.paths.characters_dir) / 'thumbs'
        img_dir   = Path(cfg.paths.characters_dir) / 'images'
        idx_map, st_map = idx.get('chars', {}), state.get('chars', {})
    else:
        thumb_pref, img_pref = prefixes['artist_thumb'], prefixes['artist_img']
        thumb_dir = Path(cfg.paths.artists_dir) / 'thumbs'
        img_dir   = Path(cfg.paths.artists_dir) / 'images'
        idx_map, st_map = idx.get('artists', {}), state.get('artists', {})

    jobs, new_versions = [], {}
    for row in rows:
        slug = row[key_col]
        ver  = idx_map.get(slug, 0)
        new_versions[slug] = ver
        in_scope = full or ver != st_map.get(slug)
        if not in_scope:
            continue
        fname = sanitize_filename(row.get('trigger') or slug)
        dest = thumb_dir / (fname + '.webp')
        if not dest.exists() or ver != st_map.get(slug):
            jobs.append((f"{thumb_pref}/{_enc(fname + '.webp')}", dest))
        if with_images:
            dest = img_dir / (fname + '.png')
            if not dest.exists() or ver != st_map.get(slug):
                jobs.append((f"{img_pref}/{_enc(fname + '.png')}", dest))
    return jobs, new_versions


def plan_copyrights(char_rows, prefixes, idx, state, cfg, full):
    cdir = Path(cfg.paths.copyrights_dir) / 'thumbs'
    idx_map, st_map = idx.get('copyrights', {}), state.get('copyrights', {})
    seen, jobs, new_versions = set(), [], {}
    for row in char_rows:
        cp = row.get('copyright')
        if not cp or cp in seen:
            continue
        seen.add(cp)
        fname = sanitize_filename(cp) + '.webp'
        ver = idx_map.get(fname, 0)
        new_versions[fname] = ver
        if full or ver != st_map.get(fname):
            dest = cdir / fname
            if not dest.exists() or ver != st_map.get(fname):
                jobs.append((f"{prefixes['copyright_thumb']}/{_enc(fname)}",
                             dest))
    return jobs, new_versions


# ---- main ----------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--token', default=os.environ.get('ANIMADEX_IMPORT_TOKEN'),
                    help='Export token (or set ANIMADEX_IMPORT_TOKEN).')
    ap.add_argument('--site', default=DEFAULT_SITE,
                    help=f'Site base URL (default {DEFAULT_SITE}).')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--full',  action='store_true',
                   help='Force a full import (default: auto).')
    g.add_argument('--delta', action='store_true',
                   help='Force a delta update (default: auto).')
    ap.add_argument('--with-images', action='store_true',
                    help='Also download full-resolution PNGs (large!).')
    ap.add_argument('--concurrency', type=int, default=8)
    ap.add_argument('--dry-run', action='store_true',
                    help='Plan only; download and ingest nothing.')
    ap.add_argument('--r2-base',
                    help='Override the R2 base URL from the manifest '
                         '(for testing against a mirror).')
    args = ap.parse_args(argv)
    if not args.token:
        ap.error('a token is required (--token or ANIMADEX_IMPORT_TOKEN)')

    cfg = load_config()
    ensure_dirs(cfg)
    state_path = Path(cfg.paths.data_dir) / STATE_NAME
    state = _load_state(state_path)

    # full when forced, or auto-full on a first-ever import.
    want_full = args.full or (not args.delta and state.get('version') is None)

    print(f"Contacting {args.site} …")
    man, did_full = fetch_manifest(args.site, args.token, want_full)
    orig_base = man['r2_base'].rstrip('/')
    r2 = (args.r2_base or orig_base).rstrip('/')
    # --r2-base (testing) redirects every R2 URL to a mirror.
    if r2 != orig_base:
        man['csv'] = {k: v.replace(orig_base, r2)
                      for k, v in man['csv'].items()}
        man['index_url'] = man['index_url'].replace(orig_base, r2)
    pref = {k: f"{r2}/{v}" for k, v in man['prefixes'].items()}
    print(f"Catalogue version {man['version']}  ·  mode: "
          f"{'FULL' if did_full else 'delta'}"
          f"{'  (+full images)' if args.with_images else ''}")

    # CSVs land under data_dir/import/.
    imp = Path(cfg.paths.data_dir) / 'import'
    imp.mkdir(parents=True, exist_ok=True)
    chars_csv, artists_csv = imp / 'characters.csv', imp / 'artists.csv'
    if not args.dry_run:
        download(man['csv']['characters'], chars_csv)
        download(man['csv']['artists'],    artists_csv)
    else:                                   # need them locally to plan
        download(man['csv']['characters'], chars_csv)
        download(man['csv']['artists'],    artists_csv)
    _, idx = get_json(man['index_url'])

    char_rows   = _read_csv(chars_csv)
    artist_rows = _read_csv(artists_csv)

    cjobs, cver = plan_files(char_rows, 'character', pref, idx, state, cfg,
                             did_full, args.with_images)
    ajobs, aver = plan_files(artist_rows, 'artist', pref, idx, state, cfg,
                             did_full, args.with_images)
    pjobs, pver = plan_copyrights(char_rows, pref, idx, state, cfg, did_full)
    jobs = cjobs + ajobs + pjobs

    print(f"  characters: {len(char_rows):,} rows · {len(cjobs):,} files to fetch")
    print(f"  artists:    {len(artist_rows):,} rows · {len(ajobs):,} files to fetch")
    print(f"  copyrights: {len(pver):,} series · {len(pjobs):,} thumbs to fetch")
    print(f"  total downloads: {len(jobs):,}")
    if jobs[:1]:
        print(f"  e.g. {jobs[0][0]}")

    if args.dry_run:
        print("\nDry run -- nothing downloaded or ingested.")
        return

    # Download with a small thread pool; tolerate individual 404s (a
    # thumbnail may legitimately be missing for a brand-new row).
    done = fail = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(download, url, dest): url for url, dest in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                fut.result()
                done += 1
            except urllib.error.HTTPError as e:
                fail += 1
                if e.code != 404:
                    print(f"  ! {futs[fut]} -> HTTP {e.code}")
            except Exception as e:                       # noqa: BLE001
                fail += 1
                print(f"  ! {futs[fut]} -> {e}")
            if i % 500 == 0 or i == len(jobs):
                print(f"  downloaded {done:,}/{len(jobs):,} "
                      f"({fail} skipped/failed)")

    # Bulk-ingest the CSVs into SQLite (thumbnails already on disk -> the
    # web app cache-busts by file mtime, so no image step is needed).
    from animadex import db
    from animadex.pipeline.ingest import build_db
    conn = db.connect_rw(cfg.paths.database)
    try:
        nc = build_db(conn, str(chars_csv),   'characters')
        na = build_db(conn, str(artists_csv), 'artists')
    finally:
        conn.close()
    print(f"Ingested {nc:,} characters and {na:,} artists into the local DB.")

    # Persist state for the next (delta) run.
    state = {'version': man['version'], 'chars': cver, 'artists': aver,
             'copyrights': pver}
    state_path.write_text(json.dumps(state), encoding='utf-8')
    print(f"\nDone. Start the gallery with  run.bat  (or run.sh).")


if __name__ == '__main__':
    main()
