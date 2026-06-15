def normalize_telegram_handle(handle):
    if handle is None:
        return None

    normalized_handle = handle.strip().lstrip("@").lower()
    return normalized_handle or None
