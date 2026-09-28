from domain import Line
from service import OrderService


def create_order(payload: dict, service: OrderService) -> dict:
    """Transport adapter; input validation errors propagate to its caller."""
    lines = [Line(**line) for line in payload["lines"]]
    order = service.create(payload["key"], lines, payload.get("discount", 0))
    return {"key": order.key, "total": order.total, "status": order.status}
