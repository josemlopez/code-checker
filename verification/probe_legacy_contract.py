"""Reproduce the sample's idempotency violation without modifying its files."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "dispatch"))
import legacy


def probe():
    legacy.CACHE.clear()
    with patch.object(legacy, "send_confirmation") as notification:
        first = legacy.process({"key":"audit-001", "lines":[{"quantity":1,"unit_price":100}]})
        second = legacy.process({"key":"audit-001", "lines":[{"quantity":1,"unit_price":200}]})
        observed = {"first_total":first["total"], "second_total":second["total"], "stored_total":legacy.CACHE["audit-001"]["total"], "notifications":notification.call_count}
    expected = {"first_total":100,"second_total":100,"stored_total":100,"notifications":1}
    return {"task":"Contrato de idempotencia de legacy.process", "accepted":observed == expected,
            "expected":expected,"observed":observed,
            "scope":"Dos llamadas secuenciales. Notificación sustituida por un mock. Sin pruebas de concurrencia ni entrega real."}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    result = probe()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["accepted"] else 1)
