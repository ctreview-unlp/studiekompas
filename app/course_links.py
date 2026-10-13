"""
Turns course names in a reply into links to their information page.

Done on the server instead of asking the model, because here the exact
names and URLs are known: every course that's mentioned gets a link, the
link can't point at a wrong or invented page, and it works even when the
model forgets. The widget renders a link inside a sentence as plain blue
link text, and keeps buttons for links on a line of their own (enrolling,
email), so the course names read like a normal web page.
"""

import re

# An existing [label](target) link, so names inside one are left alone.
EXISTING_LINK = re.compile(r"\[[^\]]+\]\([^)\s]+\)")
# "certificering: NLP Practitioner (ABNLP)" names a certificate, not the course.
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


def link_course_names(text: str, courses: list[dict]) -> str:
    """Link the first mention of each course in `text` to its info page."""
    linkable = {c["name"].lower(): c["url"] for c in courses if c.get("name") and c.get("url")}
    if not linkable:
        return text

    # Longest names first, so "NLP Practitioner Intensief" wins over "NLP Practitioner".
    names = sorted(linkable, key=len, reverse=True)
    pattern = re.compile(
        r"(?<![\w\[])(" + "|".join(re.escape(n) for n in names) + r")(?!\w)",
        re.IGNORECASE,
    )
    # Courses the model already linked itself count as linked.
    linked: set[str] = {
        m.group(1).lower()
        for m in re.finditer(r"\[([^\]]+)\]\(", text)
        if m.group(1).lower() in linkable
    }

    def link(match: re.Match) -> str:
        name = match.group(1)
        key = name.lower()
        if key in linked or not refers_to_course(match.string[:match.start()]):
            return name
        linked.add(key)
        return f"[{name}]({linkable[key]})"

    # Only replace in the text between existing links.
    parts, last = [], 0
    for existing in EXISTING_LINK.finditer(text):
        parts.append(pattern.sub(link, text[last:existing.start()]))
        parts.append(existing.group(0))
        last = existing.end()
    parts.append(pattern.sub(link, text[last:]))
    return "".join(parts)
