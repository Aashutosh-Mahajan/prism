"""Words that mean the same thing in code, so a request can use its own vocabulary.

People ask for "how long a code is good for" and the code says `LIFETIME_MINUTES`; they say
"signing in" and the code says `auth`. Matching only the request's own words misses these.
Each group below is a set of near-synonyms *as they appear in code and UI text*. A request word
also searches for the others in its group at reduced weight (see `task_pack._query_terms`), so
an exact match still outranks a related one. The table is deliberately small and plain: it is
deterministic and local, and a wrong expansion only adds a weaker candidate.
"""

from __future__ import annotations

from prism.navigator.text import tokenize

GROUPS: tuple[tuple[str, ...], ...] = (
    (
        "expire",
        "expiry",
        "expiration",
        "lifetime",
        "validity",
        "valid",
        "ttl",
        "timeout",
        "duration",
        "long",
    ),
    ("login", "signin", "sign", "authenticate", "auth", "logon", "credential"),
    ("logout", "signout"),
    ("redirect", "landing", "navigate", "route"),
    ("remove", "delete", "destroy", "erase", "drop"),
    ("create", "insert", "register"),
    ("edit", "modify", "patch"),
    ("fetch", "retrieve", "load"),
    ("send", "dispatch", "deliver", "notify", "email"),
    ("error", "exception", "failure", "fault"),
    ("user", "account", "member", "customer"),
    ("price", "cost", "amount", "charge", "fee"),
    ("discount", "coupon", "promo", "rebate"),
    ("config", "setting", "option", "preference"),
    ("password", "passcode", "secret"),
    ("permission", "access", "authorize", "privilege", "role"),
    ("cache", "memoize"),
    ("log", "logging", "audit"),
    ("payment", "billing", "checkout"),
    ("order", "purchase", "booking"),
)

EXPANSION_WEIGHT = 0.5


def _build() -> dict[str, tuple[str, ...]]:
    related: dict[str, set[str]] = {}
    for group in GROUPS:
        stems = {t for word in group for t in tokenize(word)}
        for stem in stems:
            related.setdefault(stem, set()).update(stems - {stem})
    return {stem: tuple(sorted(others)) for stem, others in related.items()}


_RELATED = _build()


def related_terms(term: str) -> tuple[str, ...]:
    """Stemmed terms that mean about the same as the stemmed `term` (empty if none)."""
    return _RELATED.get(term, ())
