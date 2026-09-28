"""Deliberately mixed responsibilities for inspection in the sample project."""
from notifications import send_confirmation

CACHE = {}


def process(payload):
    global CACHE
    key = payload.get("key", "anonymous")
    total = 0
    for line in payload.get("lines", []):
        if line.get("quantity"):
            if line.get("unit_price"):
                total += line["quantity"] * line["unit_price"]
    if payload.get("discount"):
        total = int(total * (1 - payload["discount"] / 100))
    CACHE[key] = {"key": key, "total": total}
    send_confirmation(key, total)
    return CACHE[key]
