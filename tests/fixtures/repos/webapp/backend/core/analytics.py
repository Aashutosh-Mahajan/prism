"""Analytics helpers shared by the dashboard endpoints.

Every endpoint builds its KPI block with build_kpis so the front end can render one shape.
"""

from datetime import timedelta

from django.utils import timezone

RANGES = {"7d": 7, "30d": 30, "90d": 90, "12m": 365, "all": None}


class Window:
    def __init__(self, key, start, end, prev_start, granularity):
        self.key = key
        self.start = start
        self.end = end
        self.prev_start = prev_start
        self.granularity = granularity

    @property
    def comparable(self):
        return self.start is not None

    def as_dict(self):
        return {"range": self.key, "start": self.start, "end": self.end}


def get_window(request):
    key = request.query_params.get("range", "12m")
    if key not in RANGES:
        key = "12m"
    days = RANGES[key]
    now = timezone.now()
    if days is None:
        return Window(key, None, now, None, "month")
    start = now - timedelta(days=days)
    return Window(key, start, now, start - timedelta(days=days), "day")


def build_kpis(current, previous, kinds, snapshot=()):
    """Pair each current value with its previous-period value.

    `snapshot` metrics describe current state, so they get no comparison.
    """
    out = {}
    for key, kind in kinds.items():
        prev = None if (previous is None or key in snapshot) else previous.get(key)
        out[key] = {"value": current.get(key), "previous": prev, "kind": kind}
    return out


def _bucket_start(day, granularity):
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    return day


PLATFORM_KINDS = {"revenue": "money", "orders": "count", "signups": "count"}
RESTAURANT_KINDS = {"revenue": "money", "orders": "count", "rating": "score"}


def platform_summary(request, current, previous):
    w = get_window(request)
    return {
        "window": w.as_dict(),
        "kpis": build_kpis(current, previous if w.comparable else None, PLATFORM_KINDS),
    }


def restaurant_summary(request, current, previous):
    w = get_window(request)
    return {
        "window": w.as_dict(),
        "kpis": build_kpis(
            current, previous if w.comparable else None, RESTAURANT_KINDS, ("rating",)
        ),
    }
