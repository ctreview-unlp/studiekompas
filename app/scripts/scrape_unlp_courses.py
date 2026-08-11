"""
Scrape course data directly from UNLP's own public website.

Since the site renders live Carta Online data via a WordPress plugin (no
login or API key needed to read it — it's just a public page), this reads
the same information a visitor sees, structures it, and feeds it into the
existing ingestion pipeline.

Usage:
    python -m app.scripts.scrape_unlp_courses            # scrape + print only
    python -m app.scripts.scrape_unlp_courses --ingest    # scrape + write to DB

Data extracted per course:
  1. General course info (name, prerequisites, description, duration,
     certification, a representative price) — via Elementor widget parsing.
  2. Scheduled offers (date, location, trainer, price, enrollment link,
     availability status, day-of-week pattern) — via Carta's own
     `co-offer-*` markup, a repeating block per course.
"""

import argparse
import datetime
import re
import time

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StudiekompasBot/1.0; internal course sync)"
}

DUTCH_MONTHS = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}

DUTCH_WEEKDAYS = {
    0: "maandag", 1: "dinsdag", 2: "woensdag", 3: "donderdag",
    4: "vrijdag", 5: "zaterdag", 6: "zondag",
}

WEEKDAY_ABBREV_ORDER = {"ma": 0, "di": 1, "wo": 2, "do": 3, "vr": 4, "za": 5, "zo": 6}
WEEKDAY_ABBREV_FULL = {
    "ma": "maandag", "di": "dinsdag", "wo": "woensdag", "do": "donderdag",
    "vr": "vrijdag", "za": "zaterdag", "zo": "zondag",
}

COURSE_URLS = {
    "NLP": [
        ("NLP Introductiedag", "https://unlp.nl/opleidingen/nlp-introductiedag/"),
        ("NLP Practitioner", "https://unlp.nl/opleidingen/nlp-practitioner-opleiding/"),
        ("NLP Practitioner Intensief", "https://unlp.nl/opleidingen/nlp-practitioner-intensief-opleiding/"),
        ("NLP Practitioner Zomer Intensief", "https://unlp.nl/opleidingen/nlp-zomer-practitioner-intensief/"),
        ("NLP Practitioner Online", "https://unlp.nl/opleidingen/nlp-practitioner-online/"),
        ("NLP Practitioner Curacao", "https://unlp.nl/opleidingen/nlp-practitioner-intensief-curacao/"),
        ("NLP Practitioner Intensive (English)", "https://unlp.nl/opleidingen/nlp-practitioner-opleiding-english/"),
        ("NLP Master Practitioner", "https://unlp.nl/opleidingen/nlp-master-practitioner-opleiding/"),
        ("NLP Master Practitioner Intensief", "https://unlp.nl/opleidingen/nlp-master-practitioner-intensief/"),
        ("NLP Master Practitioner Online", "https://unlp.nl/opleidingen/nlp-master-practitioner-online/"),
        ("NLP Coachopleiding", "https://unlp.nl/opleidingen/opleidingen-nlp-coach/"),
        ("NLP Trainersopleiding", "https://unlp.nl/opleidingen/nlp-trainers-opleiding/"),
        ("NLP voor Jongeren", "https://unlp.nl/opleidingen/3-daagse-training-nlp-voor-jongeren/"),
    ],
    "Systemisch": [
        ("Systemisch Coachen", "https://unlp.nl/opleidingen/systemisch-coachen-opleiding/"),
        ("Familieopstellingen Basisopleiding", "https://unlp.nl/opleidingen/basisopleiding-familieopstellingen/"),
        ("Familieopstellingen Verdiepingsopleiding", "https://unlp.nl/opleidingen/verdiepingsopleiding-familieopstellingen/"),
        ("Systemisch Opsteller", "https://unlp.nl/opleidingen/systemisch-opsteller/"),
        ("Stephan Hausner Workshop", "https://unlp.nl/opleidingen/stephan-hausner/"),
        ("Systemisch Werk in Organisaties", "https://unlp.nl/opleidingen/opleiding-systemisch-werk-in-organisaties/"),
        ("Introductieworkshop Systemisch Werk in Organisaties", "https://unlp.nl/opleidingen/workshop-organisatieopstellingen/"),
        ("Samengestelde gezinnen en patchwork", "https://unlp.nl/opleidingen/workshop-samengestelde-systemen-stiefgezinnen-en-patchwork-families/"),
        ("Familieopstellingen avond", "https://unlp.nl/opleidingen/familieopstellingen-avond/"),
    ],
    "Coaching": [
        ("Stress en Burn-out Coachopleiding", "https://unlp.nl/opleidingen/stress-en-burn-out-coach/"),
        ("Post-HBO Coachopleiding", "https://unlp.nl/opleidingen/post-hbo-coach/"),
        ("Teamcoaching", "https://unlp.nl/opleidingen/post-hbo-opleiding-teamcoaching/"),
        ("Leiderschaps- en Executive Coaching", "https://unlp.nl/opleidingen/post-hbo-opleiding-leiderschaps-en-executive-coaching/"),
        ("Provocatief Coachen", "https://unlp.nl/opleidingen/2-daagse-provocatief-coachen/"),
        ("3-daagse Coachopleiding", "https://unlp.nl/opleidingen/3-daagse-nlp-coachopleiding/"),
        ("2-daagse opleiding Neurocoach", "https://unlp.nl/opleidingen/2-daagse-opleiding-neurocoach/"),
        ("Lichaamsgericht Coachen", "https://unlp.nl/opleidingen/4-daagse-lichaamsgericht-coachen-met-nlp/"),
    ],
    "Zakelijke trainingen": [
        ("Authentiek Presenteren", "https://unlp.nl/opleidingen/authentiek-presenteren/"),
    ],
    "Online": [
        ("NLP Practitioner Online", "https://unlp.nl/opleidingen/nlp-practitioner-online/"),
        ("NLP Master Practitioner Online", "https://unlp.nl/opleidingen/nlp-master-practitioner-online/"),
        ("Online Mindfulness Training", "https://unlp.nl/opleidingen/mindfulness-training-online/"),
        ("Emotional Freedom Techniques Online", "https://unlp.nl/opleidingen/eft-online-training/"),
        ("NLP Advanced - video modules", "https://unlp.nl/opleidingen/nlp-advanced-video-modules/"),
        ("NLP Essentials - video modules", "https://unlp.nl/opleidingen/nlp-essentials-video-modules/"),
    ],
    "Workshops & Events": [
        ("Coachend Leidinggeven", "https://unlp.nl/opleidingen/coachend-leidinggeven-met-nlp-2/"),
        ("Effectief Communiceren op de Werkvloer", "https://unlp.nl/opleidingen/effectief-communiceren-op-de-werkvloer/"),
        ("Transactionele Analyse", "https://unlp.nl/opleidingen/2-daagse-transactionele-analyse/"),
        ("Overdurfian Hypnotic Coaching", "https://unlp.nl/opleidingen/overdurfian-hypnotic-coaching/"),
        ("Hypno-Coaching", "https://unlp.nl/opleidingen/hypno-coaching/"),
        ("Hypno-Coaching Verdieping", "https://unlp.nl/opleidingen/hypno-coaching-verdieping/"),
        ("Training Adem voor coaches", "https://unlp.nl/opleidingen/training-adem-voor-coaches/"),
        ("Polyvagaal in de Praktijk", "https://unlp.nl/opleidingen/1-daagse-polyvagaal-in-de-praktijk/"),
        ("De Kracht van je Schaduw", "https://unlp.nl/opleidingen/2-daagse-opleiding-de-kracht-van-je-schaduw/"),
        ("Ontdek je Vrouwelijke Kracht", "https://unlp.nl/opleidingen/training-ontdek-je-vrouwelijke-kracht/"),
        ("1-daagse Feedback Geven & Ontvangen", "https://unlp.nl/opleidingen/1-daagse-feedback-geven-ontvangen-met-nlp/"),
        ("2-daagse Geweldloze Communicatie", "https://unlp.nl/opleidingen/geweldloze-communicatie-2-daagse-training/"),
        ("New Code Training", "https://unlp.nl/opleidingen/nlp-new-code-training/"),
        ("NLP voor Jongeren", "https://unlp.nl/opleidingen/3-daagse-training-nlp-voor-jongeren/"),
        ("2-daagse Emotional Freedom Techniques (EFT)", "https://unlp.nl/opleidingen/2-daagse-eft-emotional-freedom-techniques/"),
    ],
}


def find_field_after_label(soup: BeautifulSoup, label: str) -> str | None:
    """
    Elementor renders each label/value pair as two separate sibling widgets.
    Find the <h5> matching the label, go UP two levels to its outer
    .elementor-element wrapper, then look at THAT element's next sibling
    for the value.
    """
    pattern = re.compile(rf"^\s*{re.escape(label)}\s*$", re.IGNORECASE)
    label_tag = soup.find("h5", string=pattern)
    if not label_tag:
        return None

    widget_container = label_tag.parent
    if widget_container is None:
        return None
    outer_wrapper = widget_container.parent
    if outer_wrapper is None:
        return None

    next_widget = outer_wrapper.find_next_sibling("div", class_="elementor-element")
    if not next_widget:
        return None

    value_h5 = next_widget.find("h5")
    if value_h5:
        return value_h5.get_text(strip=True)

    text = next_widget.get_text(" ", strip=True)
    return text or None


def extract_price(soup: BeautifulSoup) -> str | None:
    """Grab the first € amount found on the page as a representative price."""
    text = soup.get_text(" ", strip=True)
    match = re.search(r"€\s?[\d.,]+", text)
    return match.group(0) if match else None


def parse_price_str(price_str: str | None) -> float | None:
    """Convert Dutch-formatted price strings into a plain numeric value."""
    if not price_str:
        return None
    digits_only = re.sub(r"[^\d]", "", price_str)
    return float(digits_only) if digits_only else None


def parse_dutch_date(s: str | None) -> datetime.date | None:
    """Parse '7 september 2026' style strings into a real date object."""
    if not s:
        return None
    parts = s.strip().split()
    if len(parts) != 3:
        return None
    day_str, month_name, year_str = parts
    month = DUTCH_MONTHS.get(month_name.lower())
    if not month:
        return None
    try:
        return datetime.date(int(year_str), month, int(day_str))
    except ValueError:
        return None


def parse_availability_status(article) -> str:
    """
    Read the offer's availability status from its CSS class.

    Carta does not publish an exact remaining-spot count anywhere on the
    public page — only this three-level status (co-offer-status-full,
    co-offer-status-almostfull, or neither = normal availability). This is
    the ceiling of what can be scraped; an exact number simply isn't there.
    """
    class_list = article.get("class", [])
    if "co-offer-status-full" in class_list:
        return "vol"
    if "co-offer-status-almostfull" in class_list:
        return "bijna vol"
    return "beschikbaar"


def parse_offer_days(article) -> list[str]:
    """
    Extract the unique weekday names (in Mon-Sun order) this offer's actual
    class sessions fall on, read from the offer's full planning data (every
    individual class day, not just the first start date).

    This is what lets the advisor answer "weekend variant" vs. "doordeweekse
    variant" questions honestly, using real scraped attendance patterns
    instead of guessing from the marketing variant name or just the first
    start date. A course spread across Fri/Sat/Sun sessions and one spread
    across Mon-Sat consecutive days look identical if you only look at the
    first start date — this field is what actually distinguishes them.
    """
    day_spans = article.select(".co-offer-planning-data .co-offer-planning-datestartdaynameshort")
    abbrevs_seen = []
    for span in day_spans:
        abbr = span.get_text(strip=True).lower()
        if abbr and abbr not in abbrevs_seen:
            abbrevs_seen.append(abbr)
    abbrevs_seen.sort(key=lambda a: WEEKDAY_ABBREV_ORDER.get(a, 99))
    return [WEEKDAY_ABBREV_FULL[a] for a in abbrevs_seen if a in WEEKDAY_ABBREV_FULL]


def parse_offers(soup: BeautifulSoup) -> list[dict]:
    """
    Parse every scheduled offer (date + location + trainer + price + variant
    + availability + day pattern) from a course page's Carta-rendered offer
    list (co-offer-* markup). A single course page can have several of
    these — one per scheduled date/location combination.
    """
    offers = []
    for article in soup.select("article.co-offer-item"):
        location_tag = article.select_one(".co-offer-location")
        location = location_tag.get_text(strip=True) if location_tag else None

        date_tag = article.select_one(".co-offer-next-start-date")
        start_date = parse_dutch_date(date_tag.get_text(strip=True) if date_tag else None)

        trainer_links = article.select(".co-offer-teacherlist-data a")
        trainer = ", ".join(a.get_text(strip=True) for a in trainer_links) or None

        variant_tag = article.select_one(".co-offer-priceinfo-data strong")
        variant = variant_tag.get_text(strip=True) if variant_tag else None

        price_tag = article.select_one(".co-offer-price")
        price = parse_price_str(price_tag.get_text(strip=True) if price_tag else None)

        link_tag = article.select_one("a.co-offer-register-link")
        enrollment_url = link_tag["href"] if link_tag and link_tag.has_attr("href") else None

        availability_status = parse_availability_status(article)
        lesdagen = parse_offer_days(article)

        offers.append({
            "location": location,
            "start_date": start_date,
            "trainer": trainer,
            "variant": variant,
            "price": price,
            "enrollment_url": enrollment_url,
            "availability_status": availability_status,
            "lesdagen": lesdagen,
        })
    return offers


def build_schedule_summary(offers: list[dict], max_items: int = 6) -> str | None:
    """Short human-readable summary of the next few upcoming offers, for the
    system prompt. Full detail per offer lives in course_schedules.

    Includes the weekday pattern (lesdagen) so the advisor can correctly
    answer "weekend variant" / "doordeweekse variant" questions using real
    data, and includes availability status so it can mention urgency
    honestly without ever citing an exact spot count Carta doesn't publish."""
    dated = [o for o in offers if o["start_date"]]
    dated.sort(key=lambda o: o["start_date"])
    if not dated:
        return None

    month_names_nl = {v: k for k, v in DUTCH_MONTHS.items()}
    parts = []
    for o in dated[:max_items]:
        d = o["start_date"]
        weekday = DUTCH_WEEKDAYS[d.weekday()]
        piece = f"{weekday} {d.day} {month_names_nl[d.month]} {d.year} ({o['location']}"
        if o.get("availability_status") and o["availability_status"] != "beschikbaar":
            piece += f", {o['availability_status']}"
        if o.get("lesdagen"):
            piece += f", lesdagen: {', '.join(o['lesdagen'])}"
        piece += ")"
        parts.append(piece)
    return "; ".join(parts)


def scrape_course(name: str, url: str, category: str, retries: int = 2) -> dict:
    last_error = None
    resp = None
    for _ in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25)
            resp.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            last_error = e
            time.sleep(2)
    else:
        raise last_error

    soup = BeautifulSoup(resp.text, "html.parser")

    description = None
    meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    if meta_desc and meta_desc.get("content"):
        description = meta_desc["content"].strip()

    prerequisites = find_field_after_label(soup, "Vooropleiding")
    duration = find_field_after_label(soup, "Opleidingsduur")
    certification = find_field_after_label(soup, "Certificering")
    price = extract_price(soup)

    offers = parse_offers(soup)
    upcoming_schedule = build_schedule_summary(offers)

    level = "Beginner" if not prerequisites or prerequisites.strip().lower() == "geen" else "Gevorderd"

    return {
        "name": name,
        "category": category,
        "level": level,
        "prerequisites": prerequisites,
        "description": description,
        "price": price,
        "duration": duration,
        "certification": certification,
        "url": url,
        "offers": offers,
        "upcoming_schedule": upcoming_schedule,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Actually write results into the database. Without this flag, only prints.",
    )
    args = parser.parse_args()

    results = []
    for category, courses in COURSE_URLS.items():
        for name, url in courses:
            print(f"Scraping: {name} ({url})")
            try:
                data = scrape_course(name, url, category)
                results.append(data)
                print(f"  prerequisites:      {data['prerequisites']!r}")
                print(f"  duration:           {data['duration']!r}")
                print(f"  certification:      {data['certification']!r}")
                print(f"  price:              {data['price']!r}")
                print(f"  upcoming_schedule:  {data['upcoming_schedule']!r}")
                print(f"  offers found:       {len(data['offers'])}")
                print(f"  description:        {(data['description'] or '')[:80]!r}...")
            except Exception as e:
                print(f"  FAILED: {e}")
            time.sleep(1)

    print(f"\nScraped {len(results)} course pages.")

    if not args.ingest:
        print("\nRun with --ingest to write these into the database once the output above looks right.")
        return

    from app.scripts.ingest_courses import (
        DATABASE_URL,
        VOYAGE_API_KEY,
        EMBED_MODEL,
        build_chunk_text,
    )
    import psycopg
    import voyageai

    vo = voyageai.Client(api_key=VOYAGE_API_KEY)

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            course_ids = []
            chunk_texts = []

            for course in results:
                if isinstance(course["price"], str):
                    course["price"] = parse_price_str(course["price"])
                cur.execute(
                    """
                    INSERT INTO courses (name, category, level, prerequisites, description,
                                          price, duration, next_start_date, url, upcoming_schedule,
                                          certification)
                    VALUES (%(name)s, %(category)s, %(level)s, %(prerequisites)s, %(description)s,
                            %(price)s, %(duration)s, NULL, %(url)s, %(upcoming_schedule)s,
                            %(certification)s)
                    ON CONFLICT (name) DO UPDATE SET
                        category = EXCLUDED.category,
                        level = EXCLUDED.level,
                        prerequisites = EXCLUDED.prerequisites,
                        description = EXCLUDED.description,
                        price = EXCLUDED.price,
                        duration = EXCLUDED.duration,
                        url = EXCLUDED.url,
                        upcoming_schedule = EXCLUDED.upcoming_schedule,
                        certification = EXCLUDED.certification,
                        updated_at = now()
                    RETURNING id;
                    """,
                    course,
                )
                course_id = cur.fetchone()[0]
                cur.execute("DELETE FROM course_chunks WHERE course_id = %s;", (course_id,))
                cur.execute("DELETE FROM course_schedules WHERE course_id = %s;", (course_id,))

                for offer in course.get("offers", []):
                    cur.execute(
                        """
                        INSERT INTO course_schedules (course_id, location, start_date, trainer, variant,
                                                       price, enrollment_url, availability_status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                        """,
                        (course_id, offer["location"], offer["start_date"], offer["trainer"],
                         offer["variant"], offer["price"], offer["enrollment_url"],
                         offer["availability_status"]),
                    )

                course_ids.append(course_id)
                chunk_texts.append(build_chunk_text(course))

            print(f"Embedding {len(chunk_texts)} courses in a single batch call...")
            embeddings = vo.embed(chunk_texts, model=EMBED_MODEL, input_type="document").embeddings

            for course_id, chunk_text, embedding in zip(course_ids, chunk_texts, embeddings):
                cur.execute(
                    "INSERT INTO course_chunks (course_id, chunk_text, embedding) VALUES (%s, %s, %s);",
                    (course_id, chunk_text, embedding),
                )

        conn.commit()

    print(f"Ingested {len(results)} courses into the database.")


if __name__ == "__main__":
    main()