from domain import Order


class OrderRepository:
    """In-memory repository for a single-process demonstration."""
    def __init__(self):
        self.orders: dict[str, Order] = {}

    def get(self, key: str) -> Order | None:
        return self.orders.get(key)

    def save(self, order: Order) -> None:
        self.orders[order.key] = order
