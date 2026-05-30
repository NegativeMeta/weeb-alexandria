# Import the public catalogue from animadex.net

Rather than building your own dataset, you can clone the live catalogue
from [animadex.net](https://animadex.net) into your local install — all
the character and artist metadata plus thumbnails, ready to browse
offline. A personal **export token** authorises the download and keeps it
fair-use.

## 1. Generate a token

1. Sign in at [animadex.net](https://animadex.net).
2. Open **Account → "Offline dataset export"**.
3. Click **Generate token**. The token is shown **once** — copy it now.
   (Lost it? Just generate again; the old one stops working.)

The account page also shows your token's status and, after a full pull,
how long until the next one is allowed.

## 2. Run the wizard

From the repo root:

```bat
import.bat        :: Windows
```
```bash
./import.sh        # macOS / Linux
```

The wizard asks for your token, tells you whether it'll do a full or a
delta import, and offers to also download full-resolution images. Then it
downloads everything and ingests it into your local SQLite DB. When it
finishes, start the gallery with `run.bat` / `./run.sh`.

That's it. The non-interactive script underneath is
`scripts/import_from_site.py` if you'd rather drive it yourself:

```bash
python scripts/import_from_site.py --token YOUR_TOKEN              # auto full/delta
python scripts/import_from_site.py --token YOUR_TOKEN --with-images
python scripts/import_from_site.py --token YOUR_TOKEN --full --dry-run
```

## Thumbnails vs full images

By default the import downloads **WebP thumbnails only** — a few GB, and
enough for a completely browsable gallery (search, facets, tiles all
work). Pass `--with-images` (or answer "y" in the wizard) to also pull the
full-resolution PNGs, which are **~30× larger (tens of GB)** and only
needed if you want the original image behind each tile. You can run a
thumbnails-only import now and add `--with-images` later — it'll fetch
just the PNGs.

## Full vs delta, and the 48-hour limit

- **First run** = a *full* import (everything).
- **Later runs** = a *delta*: the wizard compares the catalogue's per-row
  versions against `.animadex_import_state.json` in your data dir and
  downloads only what changed or is new. Re-runs are cheap.
- A **full** pull is limited to **once every 48 hours** per token. Inside
  that window the wizard automatically falls back to a delta, so you can
  always stay up to date — you just can't re-bootstrap the whole thing
  repeatedly. (The dataset is public; the token is for fair use and lets
  you revoke/regenerate access, not for secrecy.)

## What lands where

Files go under your configured `[paths].data_dir` (default
`../animadex-data`), in the standard layout from
[data-format.md](data-format.md):

```
import/characters.csv   import/artists.csv     (the source CSVs)
characters/thumbs/*.webp   characters/images/*.png   (images opt-in)
artists/thumbs/*.webp      artists/images/*.png
copyrights/thumbs/*.webp
.animadex_import_state.json                       (delta bookkeeping)
```

Ingestion uses `animadex build-db`, which is idempotent — re-importing
only updates changed rows. The web app cache-busts thumbnails by file
mtime, so refreshed images show up immediately after a delta.

## Troubleshooting

- **"Token rejected"** — regenerate it at `animadex.net/account`.
- **"Full download is locked for ~Nh"** — you ran a full import recently;
  the wizard continues with a delta automatically.
- **"catalogue export hasn't been published yet"** — the site operator
  hasn't built the export yet; try again later.
- A few `404`s during download are normal (a brand-new row may not have a
  thumbnail yet) and are skipped.
