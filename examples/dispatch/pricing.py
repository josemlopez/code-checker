from domain import Line


def total_for(lines: list[Line], discount_percent: int = 0) -> int:
    """Return integer cents. Reject empty orders and invalid prices/quantities."""
    if not lines:
        raise ValueError("An order requires at least one line")
    if not 0 <= discount_percent <= 100:
        raise ValueError("Discount out of range")
    for line in lines:
        if line.quantity <= 0 or line.unit_price < 0:
            raise ValueError("Invalid line")
    subtotal = sum(line.unit_price * line.quantity for line in lines)
    return subtotal * (100 - discount_percent) // 100
