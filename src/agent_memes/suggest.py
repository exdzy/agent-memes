"""Turn a free-text moment ("when the deploy fails on friday") into a few targeted meme searches."""

from __future__ import annotations

import re

STOPWORDS = set(
    """a an and are as at be been but by can could did do does doing for from had has have he her him his how i if in
    into is it its just me my of on or our out over she so some than that the their them then there these they this
    those to too up us very was we were what when where which while who why will with would you your yours i'm im it's
    gets got get going goes really about after again all also am any because before being both each few more most
    other own same should such only once here""".split()
)

# mood keyword (regex) -> searches that tend to return good reaction clips
MOODS: list[tuple[str, list[str]]] = [
    (
        r"\b(fail\w*|broke\w*|crash\w*|bug\w*|error\w*|outage|disaster|fire|burn\w*|chaos)\b",
        ["this is fine", "fail", "facepalm"],
    ),
    (
        r"\b(win\w*|won|success\w*|ship\w*|launch\w*|celebrat\w*|nailed|crushed|victory|done|finally)\b",
        ["celebration", "yes", "victory"],
    ),
    (r"\b(confus\w*|wtf|huh|what|lost|unclear|weird)\b", ["confused", "what"]),
    (r"\b(shock\w*|surpris\w*|omg|wow|unexpected|unbelievable|mind)\b", ["shocked", "mind blown", "wow"]),
    (r"\b(sad|cry\w*|depress\w*|upset|tears|heartbroken)\b", ["sad", "crying"]),
    (r"\b(angry|mad|rage|furious|annoy\w*|hate)\b", ["angry", "rage"]),
    (r"\b(awkward|cringe|embarrass\w*|oops)\b", ["awkward", "cringe"]),
    (r"\b(bored|boring|tired|sleep\w*|exhaust\w*|monday)\b", ["bored", "tired"]),
    (r"\b(money|rich|pay\w*|cash|profit|budget|expensive)\b", ["money", "make it rain"]),
    (r"\b(lol|funny|laugh\w*|haha|hilarious|joke)\b", ["laughing", "lol"]),
    (r"\b(no|nope|never|refus\w*|reject\w*|denied)\b", ["nope", "no"]),
    (r"\b(yes|agree\w*|exactly|true|correct|right)\b", ["yes", "exactly"]),
    (r"\b(hello|hi|hey|welcome|greet\w*)\b", ["hello"]),
    (r"\b(bye|goodbye|leav\w*|quit\w*|exit|out)\b", ["bye", "im out"]),
    (r"\b(thank\w*|grateful|appreciat\w*)\b", ["thank you"]),
    (r"\b(wait\w*|slow|loading|forever|patience)\b", ["waiting"]),
    (r"\b(love|heart|crush|romance)\b", ["love"]),
    (r"\b(scar\w*|fear|afraid|panic\w*|nervous|anxious)\b", ["scared", "panic"]),
    (r"\b(cool|smooth|deal|swag|boss)\b", ["deal with it", "cool"]),
    (r"\b(think\w*|hmm|ponder\w*|idea|plan)\b", ["thinking"]),
    (r"\b(dance\w*|party|hype\w*|excit\w*|lets go)\b", ["dance", "excited"]),
]


def keywords(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 2]


def candidate_queries(context: str, *, max_queries: int = 4) -> list[str]:
    text = context.lower().strip()
    queries: list[str] = []

    def add(q: str) -> None:
        q = q.strip()
        if q and q not in queries:
            queries.append(q)

    kws = keywords(text)
    words = re.findall(r"[a-z0-9']+", text)
    if 1 <= len(words) <= 4:
        add(" ".join(words))  # already a meme-ish phrase: try it verbatim first
    for pattern, searches in MOODS:
        if re.search(pattern, text):
            for s in searches[:2]:
                add(s)
    if len(kws) >= 2:
        add(" ".join(kws[:2]))
    for kw in kws[:3]:
        add(kw)
    if not queries:
        add(text[:40] or "reaction")
    return queries[:max_queries]
