def send_confirmation(key: str, total: int) -> None:
    """Demo output. A real integration would need delivery and retry semantics."""
    print(f"Order {key}: {total} cents")
