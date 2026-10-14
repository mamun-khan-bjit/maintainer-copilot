import hashlib


def fingerprint(text: str) -> dict:
    """Describe user-written text without revealing it.

    Issue text can contain other people's names, emails or pasted secrets, so logs get only a short
    hash (same text -> same hash, so log lines can be matched to each other and to the DB) and a length.
    """
    return {"sha256": hashlib.sha256(text.encode()).hexdigest()[:12], "chars": len(text)}
