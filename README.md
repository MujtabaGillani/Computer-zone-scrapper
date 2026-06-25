# Computer Zone Scraper

Scrapes product data from the login-gated reseller store
**store.computerzone.pk** into a CSV.

Each row contains: **product name, price, original price, status (In Stock /
Out of Stock / Coming Soon), image URL, description, SKU, category, product URL.**

## Setup

1. Install Python 3.9+ and the dependencies:

   ```
   pip install -r requirements.txt
   ```

2. Provide your login session cookies (the store requires you to be logged in):

   - Log in to https://store.computerzone.pk in your browser.
   - Open DevTools (F12) → **Application** tab → **Cookies** →
     `https://store.computerzone.pk`.
   - Copy the **`PHPSESSID`** and **`cz_login`** values.
   - Copy `.env.example` to `.env` and paste them in.

   ```
   PHPSESSID=your_phpsessid_value
   CZ_LOGIN=your_cz_login_value
   ```

   > These cookies expire when your browser session ends. If the scraper says
   > "session expired", just grab fresh values and update `.env`.

## Usage

Scrape the default category (Power Bank):

```
python scraper.py
```

Scrape one or more specific categories by their slug (the part of the URL after
the final `/`):

```
python scraper.py power-bank--c12
python scraper.py power-bank--c12 mouse--c5 keyboard--c7
```

Custom output file:

```
python scraper.py --out powerbanks.csv power-bank--c12
```

Output is written to `products.csv` (UTF-8 with BOM, so it opens cleanly in
Excel).

## Adding more categories

To scrape categories beyond Power Bank, find each category's slug from its page
URL and either:

- pass the slugs on the command line (above), or
- add them to the `DEFAULT_CATEGORIES` list near the top of `scraper.py`.

## Notes

- The scraper pauses 0.5s between requests to be polite to the server. Adjust
  `DELAY_SECONDS` in `scraper.py` if needed.
- `.env` (your real cookies) and `*.csv` output are git-ignored.
