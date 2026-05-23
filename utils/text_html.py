import html


def e(s: str) -> str:
    return html.escape(s or "", quote=False)
