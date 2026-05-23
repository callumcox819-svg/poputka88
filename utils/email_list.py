import re

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def parse_emails(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for part in re.split(r"[,;\s]+", line):
            part = part.strip().lower()
            if part and _EMAIL_RE.match(part) and part not in seen:
                seen.add(part)
                found.append(part)
    return found
