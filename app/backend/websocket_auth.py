"""WebSocket authentication helpers that keep credentials out of URLs."""


def bearer_from_subprotocol_header(value: str | None) -> str | None:
    parts = [part.strip() for part in (value or "").split(",") if part.strip()]
    if len(parts) != 2 or parts[0] != "takeoff-auth":
        return None
    return parts[1]
