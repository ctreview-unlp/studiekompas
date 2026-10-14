import datetime

from bs4 import BeautifulSoup

from app.scripts.scrape_unlp_courses import extract_price, parse_listed_dates, select_upcoming


def soup(html):
    return BeautifulSoup(html, "html.parser")


def test_labelled_price_wins_over_add_ons():
    page = soup(
        "<p>Deelnameprijs € 695,-</p><p>De investering in deze training is €695,-</p>"
        "<p>De investering in dit coachpakket bedraagt €395,=</p>"
        "<p>Je kunt maximaal € 15.000,- aftrekken</p>"
    )
    assert extract_price(page) == "€ 695"


def test_page_with_several_products_has_no_single_price():
    page = soup("<p>Pakket A €3.000</p><p>Pakket B €5.990</p><p>Pakket C €11.400</p>")
    assert extract_price(page) is None


def test_single_amount_is_the_price():
    assert extract_price(soup("<p>Doe mee voor €2.750</p>")) == "€2.750"


def test_dates_listed_as_text_lines():
    page = soup(
        "<p>Aanmelden gratis NLP informatieavond</p>"
        "<p>Rotterdam, 13 oktober 2026 start om 19:30. Trainer: Nicolette van der Helm</p>"
        "<p>'s-Graveland, 15 januari 2027 start om 19:30. Trainer: Karin Prince</p>"
    )
    offers = parse_listed_dates(page)
    assert [(o["location"], o["start_date"], o["trainer"], o["start_time"]) for o in offers] == [
        ("Rotterdam", datetime.date(2026, 10, 13), "Nicolette van der Helm", "19:30"),
        ("'s-Graveland", datetime.date(2027, 1, 15), "Karin Prince", "19:30"),
    ]


def test_upcoming_dates_six_months_capped_with_minimum():
    today = datetime.date(2026, 10, 13)
    day = lambda n: {"start_date": today + datetime.timedelta(days=n)}

    assert select_upcoming([day(-5), day(1)], today) == [day(1)]
    assert len(select_upcoming([day(i) for i in range(25)], today)) == 20
    assert len(select_upcoming([day(1)] + [day(300 + i) for i in range(5)], today)) == 3


def test_offline_pages_are_recognised():
    from types import SimpleNamespace
    from app.scripts.scrape_unlp_courses import is_gone

    page = lambda status, url, redirected=False: SimpleNamespace(
        status_code=status, url=url, history=[object()] if redirected else []
    )
    assert is_gone(page(404, "https://unlp.nl/opleidingen/oud/"))
    assert is_gone(page(410, "https://unlp.nl/opleidingen/oud/"))
    assert is_gone(page(200, "https://unlp.nl/", redirected=True))
    # A renamed course page that redirects to its new address is still a course.
    assert not is_gone(page(200, "https://unlp.nl/opleidingen/nlp-coach/", redirected=True))
    assert not is_gone(page(200, "https://unlp.nl/opleidingen/nlp-coach/"))
