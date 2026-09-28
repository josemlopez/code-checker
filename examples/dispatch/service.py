from domain import Line, Order
from notifications import send_confirmation
from pricing import total_for
from repository import OrderRepository


class OrderService:
    """Create orders and return existing orders for a repeated idempotency key."""
    def __init__(self, repository: OrderRepository):
        self.repository = repository

    def create(self, key: str, lines: list[Line], discount: int = 0) -> Order:
        if not key:
            raise ValueError("An idempotency key is required")
        existing = self.repository.get(key)
        if existing is not None:
            return existing
        order = Order(key, total_for(lines, discount))
        self.repository.save(order)
        send_confirmation(order.key, order.total)
        return order
