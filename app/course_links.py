"""
Turns course names in a reply into links to their information page.

Done on the server instead of asking the model, because here the exact
names and URLs are known: every course that's mentioned gets a link, the
link can't point at a wrong or invented page, and it works even when the
model forgets. The widget renders a link inside a sentence as plain blue
link text, and keeps buttons for links on a line of their own (enrolling,
email), so the course names read like a normal web page.

Each course is linked once per line: that makes every option in a list
clickable without repeating a link within one sentence or paragraph.
"""

import re

# An existing [label](target) link, so names inside one are left alone.
EXISTING_LINK = re.compile(r"\[[^\]]+\]\([^)\s]+\)")
# "certificering: NLP Practitioner (ABNLP)" names a certificate, not the course.
# Short forms starting with one of these would match ordinary sentences.
COMMON_WORDS = {"voor", "de", "het", "een", "met", "van", "en", "in", "op", "bij"}
CERTIFICATE_CONTEXT = re.compile(r"certific\w*[^.!?\n]{0,40}$", re.IGNORECASE)


def refers_to_course(preceding: str) -> bool:
    """
    False when the name is quoted or follows a mention of a certificate, as
    in 'bij de online variant staat "NLP Practitioner (ABNLP)"'. Then the
    name is a label from the course data, not the course itself, and a link
    to the course page would be misleading.
    """
    line = preceding.rsplit("\n", 1)[-1]
    inside_quotes = line.count('"') % 2 == 1 or line.rfind("“") > line.rfind("”")
    return not inside_quotes and not CERTIFICATE_CONTEXT.search(line)


def course_aliases(courses: list[dict]) -> dict[str, str]:
    """
    Map every way a course is written (lowercased) to its info page URL.
    Besides the full name, the data often names variants without the "NLP"
    prefix ("Practitioner Intensief (8 dagen)", "Master Practitioner (15
    dagen)"), so that short form counts too, as long as at least two words
    remain, it doesn't start with an everyday word ("voor jongeren" would
    match ordinary sentences) and it isn't another course's name.
    """
    names = {c["name"].lower(): c["url"] for c in courses if c.get("name") and c.get("url")}
    aliases = dict(names)
    for name, url in names.items():
        if name.startswith("nlp "):
            short = name[4:]
            words = short.split()
            if len(words) >= 2 and words[0] not in COMMON_WORDS and short not in names:
                aliases.setdefault(short, url)
    return aliases


def link_line(line: str, aliases: dict[str, str], pattern: re.Pattern) -> str:
    """Link the first mention of each course in one line of text."""
    # Courses the model already linked itself in this line count as linked.
    linked: set[str] = {
        aliases[m.group(1).lower()]
        for m in re.finditer(r"\[([^\]]+)\]\(", line)
        if m.group(1).lower() in aliases
    }

    def link(match: re.Match) -> str:
        name = match.group(1)
        url = aliases[name.lower()]
        if url in linked or not refers_to_course(match.string[:match.start()]):
            return name
        linked.add(url)
        return f"[{name}]({url})"

    # Only replace in the text between existing links.
    parts, last = [], 0
    for existing in EXISTING_LINK.finditer(line):
        parts.append(pattern.sub(link, line[last:existing.start()]))
        parts.append(existing.group(0))
        last = existing.end()
    parts.append(pattern.sub(link, line[last:]))
    return "".join(parts)


def link_course_names(text: str, courses: list[dict]) -> str:
    """
    Link course names in `text` to their info page: the first mention per
    line, so every option in a list is clickable while a name repeated in
    one sentence or paragraph is linked only once.
    """
    aliases = course_aliases(courses)
    if not aliases:
        return text

    # Longest first, so "NLP Practitioner Intensief" wins over "NLP Practitioner".
    pattern = re.compile(
        r"(?<![\w\[])(" + "|".join(re.escape(n) for n in sorted(aliases, key=len, reverse=True)) + r")(?!\w)",
        re.IGNORECASE,
    )
    return "\n".join(link_line(line, aliases, pattern) for line in text.split("\n"))
