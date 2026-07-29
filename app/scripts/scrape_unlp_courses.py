"""
Scrape course data directly from UNLP's own public website.

Since the site renders live Carta Online data via a WordPress plugin (no
login or API key needed to read it — it's just a public page), this reads
the same information a visitor sees, structures it, and feeds it into the
existing ingestion pipeline.

Usage:
    python -m app.scripts.scrape_unlp_courses            # scrape + print only
    python -m app.scripts.scrape_unlp_courses --ingest    # scrape + write to DB

IMPORTANT — this was written from page content viewed through a text-extraction
tool, not the raw HTML. The label-matching logic below is a best effort at
guessing the real DOM structure. Run this first WITHOUT --ingest, check the
printed output against the actual page in your browser, and tell me what's
wrong so we can fix the selectors — don't trust it blindly on the first run.
"""

import argparse
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StudiekompasBot/1.0; internal course sync)"
}

# Course URLs pulled from https://unlp.nl/al-onze-opleidingen/, organized by
# category. Add/remove/edit as the real catalog changes — this list is the
# only thing that should need manual updates when a new course launches.
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
    Elementor renders each label/value pair as two separate sibling widgets:

    <div class="elementor-element ... elementor-widget-heading">   <- outer wrapper
      <div class="elementor-widget-container">
        <h5>Vooropleiding</h5>                                     <- the label
      </div>
    </div>
    <div class="elementor-element ... elementor-widget-heading">   <- NEXT outer wrapper
      <div class="elementor-widget-container">
        <h5>Geen</h5>                                              <- the value
      </div>
    </div>

    So: find the <h5> matching the label, go UP two levels to its outer
    .elementor-element wrapper, then look at THAT element's next sibling
    (not the h5's own sibling) for the value.
    """
    pattern = re.compile(rf"^\s*{re.escape(label)}\s*$", re.IGNORECASE)
    label_tag = soup.find("h5", string=pattern)
    if not label_tag:
        return None

    widget_container = label_tag.parent  # .elementor-widget-container
    if widget_container is None:
        return None
    outer_wrapper = widget_container.parent  # .elementor-element
    if outer_wrapper is None:
        return None

    next_widget = outer_wrapper.find_next_sibling(
        "div", class_="elementor-element"
    )
    if not next_widget:
        return None

    # Most fields (Vooropleiding, Certificering) are a single <h5> value.
    value_h5 = next_widget.find("h5")
    if value_h5:
        return value_h5.get_text(strip=True)

    # Opleidingsduur's value is longer, multi-line text (Regulier/Intensief/
    # Online breakdown) — likely a text-editor widget, not a heading. Fall
    # back to grabbing all text in that widget instead.
    text = next_widget.get_text(" ", strip=True)
    return text or None


def extract_price(soup: BeautifulSoup) -> str | None:
    """Grab the first € amount found on the page as a representative price.
    Note: pages often list several prices (one per location/variant) —
    this returns the first, not necessarily the cheapest or most common."""
    text = soup.get_text(" ", strip=True)
    match = re.search(r"€\s?[\d.,]+", text)
    return match.group(0) if match else None

def parse_price(price_str: str | None) -> float | None:
    """
    Convert Dutch-formatted price strings like '€ 2.750', '€2.995', '€ 995,'
    into a plain numeric value the database can store.

    Dutch formatting uses '.' as a thousands separator, not a decimal point,
    and prices on this site never show cents — so stripping everything
    except digits and parsing as an integer is safe here.
    """
    if not price_str:
        return None
    digits_only = re.sub(r"[^\d]", "", price_str)
    return float(digits_only) if digits_only else None


def scrape_course(name: str, url: str, category: str) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=25)
    resp.raise_for_status()
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
                print(f"  prerequisites: {data['prerequisites']!r}")
                print(f"  duration:      {data['duration']!r}")
                print(f"  price:         {data['price']!r}")
                print(f"  description:   {(data['description'] or '')[:80]!r}...")
            except Exception as e:
                print(f"  FAILED: {e}")
            time.sleep(1)  # be polite — no need to hammer the site

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

            # First pass: upsert all course rows, collect ids + chunk text
            for course in results:
                course["price"] = parse_price(course["price"])
                cur.execute(
                    """
                    INSERT INTO courses (name, category, level, prerequisites, description,
                                          price, duration, next_start_date, url)
                    VALUES (%(name)s, %(category)s, %(level)s, %(prerequisites)s, %(description)s,
                            %(price)s, %(duration)s, NULL, %(url)s)
                    ON CONFLICT (name) DO UPDATE SET
                        category = EXCLUDED.category,
                        level = EXCLUDED.level,
                        prerequisites = EXCLUDED.prerequisites,
                        description = EXCLUDED.description,
                        price = EXCLUDED.price,
                        duration = EXCLUDED.duration,
                        url = EXCLUDED.url,
                        updated_at = now()
                    RETURNING id;
                    """,
                    course,
                )
                course_id = cur.fetchone()[0]
                cur.execute("DELETE FROM course_chunks WHERE course_id = %s;", (course_id,))

                course_ids.append(course_id)
                chunk_texts.append(build_chunk_text(course))

            # Second pass: ONE batched embedding call for everything
            print(f"Embedding {len(chunk_texts)} courses in a single batch call...")
            embeddings = vo.embed(chunk_texts, model=EMBED_MODEL, input_type="document").embeddings

            # Third pass: store each embedding against its course
            for course_id, chunk_text, embedding in zip(course_ids, chunk_texts, embeddings):
                cur.execute(
                    "INSERT INTO course_chunks (course_id, chunk_text, embedding) VALUES (%s, %s, %s);",
                    (course_id, chunk_text, embedding),
                )

        conn.commit()

    print(f"Ingested {len(results)} courses into the database.")

if __name__ == "__main__":
    main()