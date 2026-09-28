from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
    sku: str
    unit_price: int
    quantity: int


@dataclass(frozen=True)
class Order:
    key: str
    total: int
    status: str = "created"
