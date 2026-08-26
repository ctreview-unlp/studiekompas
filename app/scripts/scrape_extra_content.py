"""
Discover and ingest UNLP content that lives OUTSIDE /opleidingen/ — events,
festivals, informatieavonden, webinars, and similar offers that the main
course scraper never sees, since it only knows about pages under a fixed
URL list.

This works by reading unlp.nl's own sitemap (confirmed via robots.txt to
live at unlp.nl/sitemaps.xml), filtering out pages we already cover or that
are clearly not offers (blog posts, team pages, thank-you pages, etc.), and
then checking each remaining candidate for two signals that suggest it's a
real, page-specific, bookable offer: a price (€) and a signup/registration
link that ISN'T just a site-wide promo banner appearing on every page.
Pages without both real signals are skipped — this errs toward missing
something rather than ingesting junk.

This is heuristic, not perfect. Always run WITHOUT --ingest first and
review the candidates printed — some will still need a human judgment call.

Usage:
    python -m app.scripts.scrape_extra_content            # discover + print only
    python -m app.scripts.scrape_extra_content --ingest    # discover + write to DB
"""

import argparse
import re
import time
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from app.scripts.scrape_unlp_courses import COURSE_URLS, HEADERS, extract_price, parse_price_str

load_dotenv()

# Confirmed via https://unlp.nl/robots.txt — UNLP's real sitemap location.
CANDIDATE_SITEMAP_URLS = [
    "https://unlp.nl/sitemaps.xml",
]

# Pages matching any of these should never be treated as a bookable offer.
EXCLUDE_PATH_PATTERNS = [
    r"/kennisbank/",       # blog / articles
    r"/team/",             # trainer bio pages
    r"/over-ons",          # about pages
    r"/privacy",
    r"/privacybeleid",
    r"/disclaimer",
    r"/cookie",
    r"/bedankt",           # thank-you pages after signup
    r"/gefeliciteerd",     # confirmation pages
    r"/geboekt-",          # post-booking confirmation pages, not offers
    r"/nieuwe-homepage",   # staging page
    r"/elementor-template", # page builder drafts
    r"/category/",
    r"/tag/",
    r"/auteur/",
    r"/page/\d+",          # pagination
    r"/wp-",
    r"/locatie/",          # location landing pages, not offers themselves
    r"/algemene-voorwaarden",
    r"^https://unlp\.nl/?$",  # homepage itself
]

# Signup/registration link text to look for on a candidate page.
SIGNUP_LINK_PATTERN = re.compile(
    r"aanmeld|inschrijv|ticket|claim|reserveer|schrijf je in", re.IGNORECASE
)

# Known site-wide promo banner links — appear on nearly every page, so
# finding one of these is NOT evidence a given page is itself an offer.
KNOWN_SITEWIDE_LINKS = {"https://unlp.nl/festival/", "https://unlp.nl/festival"}


def already_covered_urls() -> set[str]:
    """URLs the main course scraper already handles — skip these here."""
    urls = set()
    for courses in COURSE_URLS.values():
        for _, url in courses:
            urls.add(url.rstrip("/"))
    return urls


def fetch_sitemap_urls(sitemap_url: str, depth: int = 0) -> list[str]:
    """Recursively follow a sitemap index down to actual page URLs."""
    if depth > 2:  # safety limit against unexpectedly deep sitemap nesting
        return []
    try:
        resp = requests.get(sitemap_url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Could not fetch sitemap {sitemap_url}: {e}")
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return []

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [el.text for el in root.findall(".//sm:loc", ns) if el.text]

    # A sitemap index contains <sitemap> entries pointing to child sitemaps;
    # a regular sitemap contains <url> entries pointing to actual pages.
    is_index = root.tag.endswith("sitemapindex")
    if is_index:
        all_urls = []
        for child_url in locs:
            all_urls.extend(fetch_sitemap_urls(child_url, depth + 1))
            time.sleep(0.5)
        return all_urls
    return locs


def is_candidate(url: str, excluded: set[str]) -> bool:
    if url.rstrip("/") in excluded:
        return False
    for pattern in EXCLUDE_PATH_PATTERNS:
        if re.search(pattern, url):
            return False
    return True


def check_offer(url: str) -> dict | None:
    """
    Fetch a candidate page and check whether it looks like a real,
    page-specific offer (has a price AND a signup link that isn't just the
    site-wide promo banner appearing on every page).
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
    except requests.exceptions.RequestException:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    price = extract_price(soup)
    if not price:
        return None

    signup_link = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        full_href = href if href.startswith("http") else f"https://unlp.nl{href}"
        if full_href.rstrip("/") in {u.rstrip("/") for u in KNOWN_SITEWIDE_LINKS}:
            continue  # skip the banner, keep looking for a real page-specific link
        if "#" in full_href:
            continue  # in-page anchor (e.g. #inschrijven), not a distinct real offer
        if SIGNUP_LINK_PATTERN.search(a.get_text(" ", strip=True)):
            signup_link = full_href
            break

    if not signup_link:
        return None

    # Prefer the actual page title (og:title or <title>) over the first <h1>,
    # since some pages have a shared banner/announcement styled as an <h1>
    # that isn't the real page name.
    og_title = soup.find("meta", attrs={"property": "og:title"})
    title_tag = soup.find("title")
    if og_title and og_title.get("content"):
        name = og_title["content"].strip()
    elif title_tag:
        name = title_tag.get_text(strip=True).split("|")[0].split("-")[0].strip()
    else:
        h1 = soup.find("h1")
        name = h1.get_text(strip=True) if h1 else url

    meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    description = meta_desc["content"].strip() if meta_desc and meta_desc.get("content") else ""

    return {
        "name": name,
        "category": "Overig",
        "level": "Beginner",
        "prerequisites": "Geen",
        "description": description,
        "price": parse_price_str(price),
        "duration": None,
        "certification": None,
        "upcoming_schedule": None,
        "url": url,
        "signup_link": signup_link,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingest", action="store_true")
    args = parser.parse_args()

    all_urls = []
    for candidate_url in CANDIDATE_SITEMAP_URLS:
        print(f"Trying sitemap at {candidate_url} ...")
        try:
            resp = requests.get(candidate_url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                print(f"  Found it.")
                all_urls = fetch_sitemap_urls(candidate_url)
                break
            else:
                print(f"  {resp.status_code}, trying next...")
        except requests.exceptions.RequestException as e:
            print(f"  Failed: {e}")

    if not all_urls:
        print("\nCould not find a working sitemap at any of the usual locations.")
        print("Check manually: open https://unlp.nl/robots.txt in a browser")
        print("and look for a line starting with 'Sitemap:' — that's the real URL.")
        return

    print(f"\nFound {len(all_urls)} total URLs in sitemap.\n")

    excluded = already_covered_urls()
    candidates = [u for u in all_urls if is_candidate(u, excluded)]
    print(f"{len(candidates)} candidate URLs after filtering known/excluded pages.\n")

    found_offers = []
    for url in candidates:
        offer = check_offer(url)
        if offer:
            found_offers.append(offer)
            print(f"FOUND OFFER: {offer['name']}")
            print(f"  url:    {offer['url']}")
            print(f"  price:  € {offer['price']}")
            print(f"  signup: {offer['signup_link']}")
            print(f"  desc:   {offer['description'][:100]}...")
            print()
        time.sleep(0.5)

    print(f"\n{len(found_offers)} likely offers found outside /opleidingen/.")

    if not args.ingest:
        print("\nReview the above carefully, then run with --ingest to add them.")
        return

    from app.scripts.ingest_courses import DATABASE_URL, VOYAGE_API_KEY, EMBED_MODEL, build_chunk_text
    import psycopg
    import voyageai

    vo = voyageai.Client(api_key=VOYAGE_API_KEY)

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            course_ids = []
            chunk_texts = []

            for offer in found_offers:
                offer["upcoming_schedule"] = (
                    f"aanmelden via: {offer['signup_link']}" if offer["signup_link"] else None
                )
                cur.execute(
                    """
                    INSERT INTO courses (name, category, level, prerequisites, description,
                                          price, duration, next_start_date, url, upcoming_schedule,
                                          certification)
                    VALUES (%(name)s, %(category)s, %(level)s, %(prerequisites)s, %(description)s,
                            %(price)s, %(duration)s, NULL, %(url)s, %(upcoming_schedule)s,
                            %(certification)s)
                    ON CONFLICT (name) DO UPDATE SET
                        description = EXCLUDED.description,
                        price = EXCLUDED.price,
                        upcoming_schedule = EXCLUDED.upcoming_schedule,
                        updated_at = now()
                    RETURNING id;
                    """,
                    offer,
                )
                course_id = cur.fetchone()[0]
                cur.execute("DELETE FROM course_chunks WHERE course_id = %s;", (course_id,))

                course_ids.append(course_id)
                chunk_texts.append(build_chunk_text(offer))

            print(f"Embedding {len(chunk_texts)} offers in a single batch call...")
            embeddings = vo.embed(chunk_texts, model=EMBED_MODEL, input_type="document").embeddings

            for course_id, chunk_text, embedding in zip(course_ids, chunk_texts, embeddings):
                cur.execute(
                    "INSERT INTO course_chunks (course_id, chunk_text, embedding) VALUES (%s, %s, %s);",
                    (course_id, chunk_text, embedding),
                )

        conn.commit()

    print(f"Ingested {len(found_offers)} offers into the database.")


if __name__ == "__main__":
    main()