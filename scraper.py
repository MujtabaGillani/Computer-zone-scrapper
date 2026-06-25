"""
Computer Zone (store.computerzone.pk) catalog scraper.

The store is login-gated, so the scraper authenticates using the session
cookies (PHPSESSID + cz_login) you copy from your logged-in browser into a
.env file. It crawls one or more category pages, follows every product link,
and writes the product details to a CSV.

Usage:
    python scraper.py                      # scrape the default categories
    python scraper.py power-bank--c12      # scrape specific category slug(s)
    python scraper.py --out my_file.csv power-bank--c12

To add more categories later, either pass their slugs on the command line or
add them to DEFAULT_CATEGORIES below. A category slug is the last part of its
URL, e.g. https://store.computerzone.pk/power-bank--c12  ->  power-bank--c12
"""

import argparse
import csv
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://store.computerzone.pk/"

# Categories scraped when none are given on the command line.
# Add more slugs here as you discover them (the part after the final "/").
DEFAULT_CATEGORIES = [
    "power-bank--c12",
]

# CSV columns, in order.
FIELDNAMES = [
    "product_name",
    "price",
    "original_price",
    "status",
    "image",
    "image_count",
    "description",
    "sku",
    "category",
    "product_url",
]

DELAY_SECONDS = 0.5  # be polite between requests


def load_cookies():
    """Read session cookies from the .env file (falling back to real env vars)."""
    env = {}
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()

    phpsessid = env.get("PHPSESSID") or os.environ.get("PHPSESSID")
    cz_login = env.get("CZ_LOGIN") or os.environ.get("CZ_LOGIN")

    if not phpsessid or not cz_login:
        sys.exit(
            "ERROR: Missing cookies. Copy .env.example to .env and fill in "
            "PHPSESSID and CZ_LOGIN from your logged-in browser."
        )
    return {"PHPSESSID": phpsessid, "cz_login": cz_login}


def make_session(cookies):
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        }
    )
    session.cookies.update(cookies)
    return session


def is_logged_out(html):
    """The site bounces logged-out requests to a login redirect stub."""
    return "URL='login" in html or len(html) < 500


def get(session, url):
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"  # page is UTF-8; avoid requests' latin-1 guess
    if is_logged_out(resp.text):
        sys.exit(
            "ERROR: Session expired / not logged in (got the login redirect).\n"
            "Refresh PHPSESSID and CZ_LOGIN in your .env from a logged-in "
            "browser tab and run again."
        )
    return resp.text


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def absolute_url(href):
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return BASE_URL + href.lstrip("/")


def extract_product_links(html):
    """Return ordered, de-duplicated product page URLs from a category page."""
    soup = BeautifulSoup(html, "lxml")
    links = []
    seen = set()
    for card in soup.select("div.product__item"):
        a = card.select_one("div.product-image a[href], .product__content-3 h6 a[href]")
        if not a:
            continue
        href = a.get("href", "").strip()
        if not href.endswith(".html"):
            continue
        url = absolute_url(href)
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def parse_price_block(soup):
    """Return (current_price, original_price) as strings, e.g. ('PKR 2,475', '2,550')."""
    price_el = soup.select_one("div.price")
    if not price_el:
        return "", ""
    original = ""
    del_el = price_el.find("del")
    if del_el:
        original = clean(del_el.get_text())
        del_el.extract()  # remove so it doesn't pollute the current price
    current = clean(price_el.get_text())
    return current, original


def parse_status(soup):
    """Find the 'Availability:' value (e.g. 'In Stock' / 'Out of Stock')."""
    # Primary: the dedicated stock block, e.g. <h5>Availability: <span>...</span></h5>
    stock = soup.select_one("div.product-stock span")
    if stock:
        value = clean(stock.get_text())
        if value:
            return value
    # Fallback: a visible (non-script) "Availability:" label.
    for el in soup.find_all(["h5", "h6", "p", "div", "span", "li"]):
        text = clean(el.get_text(" "))
        m = re.search(r"Availability\s*:?\s*(Out of Stock|In Stock)", text, re.I)
        if m:
            return m.group(1)
    return ""


def parse_description(soup):
    """Prefer the full Description tab; fall back to the short features line."""
    desc = soup.select_one("#des .product__details-des-wrapper, #des")
    if desc:
        text = clean(desc.get_text(" "))
        if text:
            return text
    short = soup.select_one(".features-des")
    return clean(short.get_text(" ")) if short else ""


def meta_content(soup, prop):
    el = soup.find("meta", attrs={"property": prop})
    return el.get("content", "").strip() if el else ""


def parse_title(soup):
    """Full product title. The site truncates <title>/og:title to ~70 chars,
    so prefer the breadcrumb's active item, which carries the complete name."""
    crumb = soup.select_one("ol.breadcrumb li.breadcrumb-item.active")
    if crumb:
        title = clean(crumb.get_text())
        if title:
            return title
    name = meta_content(soup, "og:title")
    if name:
        return name
    title = soup.find("title")
    return clean(title.get_text()).split(" - ")[0] if title else ""


def parse_images(soup):
    """Return all gallery image URLs (full-size), main image first, de-duplicated."""
    urls = []
    seen = set()
    for img in soup.select("img.xzoom-gallery5"):
        url = absolute_url(img.get("xpreview") or img.get("src"))
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    if not urls:  # fall back to the single main image, then og:image
        main = soup.select_one(".product-details img")
        if main:
            url = absolute_url(main.get("xoriginal") or main.get("src"))
            if url:
                urls.append(url)
    if not urls:
        og = meta_content(soup, "og:image")
        if og:
            urls.append(og)
    return urls


def parse_product(html, url, category):
    soup = BeautifulSoup(html, "lxml")

    name = parse_title(soup)
    images = parse_images(soup)
    current_price, original_price = parse_price_block(soup)
    status = parse_status(soup)
    description = parse_description(soup)

    sku_el = soup.select_one("span.sku")
    sku = clean(sku_el.get_text()) if sku_el else ""

    return {
        "product_name": name,
        "price": current_price,
        "original_price": original_price,
        "status": status,
        "image": " | ".join(images),
        "image_count": len(images),
        "description": description,
        "sku": sku,
        "category": category,
        "product_url": url,
    }


def main():
    parser = argparse.ArgumentParser(description="Scrape Computer Zone catalog to CSV.")
    parser.add_argument(
        "categories",
        nargs="*",
        default=[],
        help="Category slugs to scrape (default: %s)" % ", ".join(DEFAULT_CATEGORIES),
    )
    parser.add_argument("--out", default="products.csv", help="Output CSV path.")
    args = parser.parse_args()

    categories = args.categories or DEFAULT_CATEGORIES
    cookies = load_cookies()
    session = make_session(cookies)

    rows = []
    for category in categories:
        cat_url = absolute_url(category)
        print(f"\n[category] {cat_url}")
        cat_html = get(session, cat_url)
        links = extract_product_links(cat_html)
        print(f"  found {len(links)} products")

        for i, url in enumerate(links, 1):
            try:
                html = get(session, url)
                row = parse_product(html, url, category)
                rows.append(row)
                print(f"  [{i}/{len(links)}] {row['product_name'][:60]} | "
                      f"{row['price']} | {row['status']}")
            except requests.RequestException as exc:
                print(f"  [{i}/{len(links)}] FAILED {url}: {exc}")
            time.sleep(DELAY_SECONDS)

    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. Wrote {len(rows)} products to {args.out}")


if __name__ == "__main__":
    main()
