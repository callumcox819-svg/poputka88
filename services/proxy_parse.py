"""Парсинг строк прокси (из happy88)."""
from __future__ import annotations
import logging
import re
from typing import Dict, Optional
logger = logging.getLogger(__name__)
_HOST_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_HOST_IPV6_RE = re.compile(r"^\[?[0-9a-fA-F:]+\]?$")  # rough
_HOST_HAS_DOT_RE = re.compile(r"\.")  # domain usually has dot
_HOST_HAS_DIGIT_RE = re.compile(r"\d")
_BAD_HOST_WORDS = {
    "тип", "типпрокси", "прокси", "host", "хост", "порт", "port",
    "логин", "login", "user", "username", "пароль", "password", "pass",
}

def _is_probable_host(host: str) -> bool:
    """Р§С‚РѕР±С‹ РЅРµ РїСЂРёРЅРёРјР°С‚СЊ 'РџРѕСЂС‚' РєР°Рє host."""
    if not host:
        return False
    h = host.strip()
    hl = h.lower()

    # СЏРІРЅРѕ РјСѓСЃРѕСЂРЅС‹Рµ СЃР»РѕРІР°
    if hl in _BAD_HOST_WORDS:
        return False

    # IPv4
    if _HOST_IPV4_RE.match(h):
        # РіСЂСѓР±Рѕ РїСЂРѕРІРµСЂРёРј РѕРєС‚РµС‚С‹
        try:
            parts = [int(x) for x in h.split(".")]
            if all(0 <= p <= 255 for p in parts):
                return True
        except Exception:
            return False

    # IPv6
    if ":" in h and _HOST_IPV6_RE.match(h):
        return True

    # РґРѕРјРµРЅС‹: РѕР±С‹С‡РЅРѕ РµСЃС‚СЊ С‚РѕС‡РєР° РёР»Рё С†РёС„СЂР° (РјРЅРѕРіРёРµ РїСЂРѕРєСЃРё: proxy123.domain.com)
    if _HOST_HAS_DOT_RE.search(h) or _HOST_HAS_DIGIT_RE.search(h):
        return True

    return False


def _normalize_proxy_type(t: str | None) -> str:
    """РўРѕР»СЊРєРѕ SOCKS5 РґР»СЏ СЂР°СЃСЃС‹Р»РєРё."""
    t = (t or "socks5").strip().lower()
    if t in ("socks", "sock5", "socksv5"):
        return "socks5"
    if t in ("socks5h",):
        return "socks5h"
    if t in ("socks5",):
        return "socks5"
    if t in ("http", "https"):
        return "http"
    if t.startswith("socks"):
        return "socks5"
    return "socks5"


def reject_non_socks5(parsed: dict) -> Optional[str]:
    pt = _normalize_proxy_type(parsed.get("type"))
    if pt in ("http", "https"):
        return "РџРѕРґРґРµСЂР¶РёРІР°РµС‚СЃСЏ С‚РѕР»СЊРєРѕ SOCKS5. HTTP/HTTPS РїСЂРѕРєСЃРё РЅРµ РїРѕРґС…РѕРґСЏС‚ РґР»СЏ СЂР°СЃСЃС‹Р»РєРё."
    parsed["type"] = "socks5"
    return None


def _strip_comments(s: str) -> str:
    """СѓР±РёСЂР°РµРј РєРѕРјРјРµРЅС‚Р°СЂРёРё С‚РёРїР° '... # comment'"""
    if not s:
        return ""
    s = s.strip().strip('"').strip("'")
    # СЂРµР¶РµРј РїРѕ # РµСЃР»Рё СЌС‚Рѕ РЅРµ С‡Р°СЃС‚СЊ РїР°СЂРѕР»СЏ/Р»РѕРіРёРЅР° (РІ РїСЂРѕРєСЃРё РїРѕС‡С‚Рё РЅРµ РІСЃС‚СЂРµС‡Р°РµС‚СЃСЏ)
    if "#" in s:
        s = s.split("#", 1)[0].strip()
    return s


# ======================
#  РџР°СЂСЃРµСЂ СЃС‚СЂРѕРєРё/Р±Р»РѕРєР° РїСЂРѕРєСЃРё
# ======================

def parse_proxy_string(raw: str) -> Optional[dict]:
    """
    РџРѕРґРґРµСЂР¶РёРІР°РµРјС‹Рµ С„РѕСЂРјР°С‚С‹ (Рё РµС‰С‘ РєСѓС‡Р° РІР°СЂРёР°С†РёР№):

      URL-С„РѕСЂРјС‹:
        - http://user:pass@ip:port
        - https://user:pass@ip:port
        - socks5://user:pass@ip:port
        - socks5://ip:port

      РљР»Р°СЃСЃРёРєР°:
        - ip:port
        - ip:port:user:pass
        - ip:port:user:pass:socks5

      Р‘СЂР°СѓР·РµСЂРЅС‹Рµ:
        - user:pass@ip:port
        - ip:port@user:pass

    Р’Р°Р¶РЅРѕ: РјС‹ РќР• С…РѕС‚РёРј РїСЂРёРЅРёРјР°С‚СЊ СЃС‚СЂРѕРєРё С‚РёРїР° "РџРѕСЂС‚: 10811" РєР°Рє РїСЂРѕРєСЃРё.
    """
    raw = _strip_comments(raw)
    if not raw:
        return None

    # ---------- 1) URL С„РѕСЂРјР°С‚ ----------
    if "://" in raw:
        from urllib.parse import urlsplit
        try:
            u = urlsplit(raw)
            scheme = _normalize_proxy_type(u.scheme)
            host = u.hostname
            port = u.port
            user = u.username
            pwd = u.password
            if not host or not port or not _is_probable_host(host):
                return None
            return {
                "host": host,
                "port": int(port),
                "username": user,
                "password": pwd,
                "type": scheme,
            }
        except Exception as e:
            logger.warning("URL proxy parse failed for '%s': %s", raw, e)
            return None

    # ---------- 2) user:pass@host:port ----------
    if "@" in raw:
        # A) user:pass@host:port(:type?)  РёР»Рё user:pass@host:port|type
        try:
            left, right = raw.rsplit("@", 1)
            # РІРѕР·РјРѕР¶РµРЅ СЃСѓС„С„РёРєСЃ :type РїРѕСЃР»Рµ port
            proto = None

            # right РјРѕР¶РµС‚ Р±С‹С‚СЊ host:port РёР»Рё host:port:type
            rparts = right.split(":")
            if len(rparts) >= 2:
                host = rparts[0].strip()
                port_s = rparts[1].strip()
                if len(rparts) >= 3:
                    proto = rparts[2].strip()
                if not _is_probable_host(host):
                    raise ValueError("bad host")
                port_i = int(port_s)

                if ":" in left:
                    user, pwd = left.split(":", 1)
                else:
                    user, pwd = left, ""

                return {
                    "host": host,
                    "port": port_i,
                    "username": user or None,
                    "password": pwd or None,
                    "type": _normalize_proxy_type(proto or "socks5"),
                }
        except Exception:
            pass

        # B) host:port@user:pass
        try:
            hostport, creds = raw.split("@", 1)
            if ":" not in hostport or ":" not in creds:
                raise ValueError("not host:port@user:pass")
            host, port_s = hostport.split(":", 1)
            user, pwd = creds.split(":", 1)
            if not _is_probable_host(host):
                raise ValueError("bad host")
            return {
                "host": host.strip(),
                "port": int(port_s.strip()),
                "username": user.strip() or None,
                "password": pwd.strip() or None,
                "type": "socks5",
            }
        except Exception:
            pass

    # ---------- 3) С‡РµСЂРµР· ':' ----------
    parts = raw.split(":")
    parts = [p.strip() for p in parts if p is not None]

    # ip:port
    if len(parts) == 2:
        host, port = parts
        if not _is_probable_host(host):
            return None
        try:
            port_i = int(port)
        except ValueError:
            return None
        return {
            "host": host,
            "port": port_i,
            "username": None,
            "password": None,
            "type": "socks5",
        }

    # ip:port:user:pass
    if len(parts) == 4:
        host, port, user, pwd = parts
        if not _is_probable_host(host):
            return None
        try:
            port_i = int(port)
        except ValueError:
            return None
        return {
            "host": host,
            "port": port_i,
            "username": user or None,
            "password": pwd or None,
            "type": "socks5",
        }

    # ip:port:user:pass[:type] вЂ” РїР°СЂРѕР»СЊ РјРѕР¶РµС‚ СЃРѕРґРµСЂР¶Р°С‚СЊ ':'
    if len(parts) >= 4:
        host, port, user = parts[0], parts[1], parts[2]
        if not _is_probable_host(host):
            return None
        try:
            port_i = int(port)
        except ValueError:
            return None
        tail = parts[3:]
        proto = None
        if len(tail) >= 2 and _normalize_proxy_type(tail[-1]) in ("socks5", "socks5h", "http", "https"):
            proto = tail[-1]
            pwd = ":".join(tail[:-1])
        else:
            pwd = ":".join(tail)
        return {
            "host": host,
            "port": port_i,
            "username": user or None,
            "password": pwd or None,
            "type": _normalize_proxy_type(proto or "socks5"),
        }

    return None


def parse_proxy_block(text: str) -> Optional[dict]:
    """
    РџР°СЂСЃРёС‚ "РєР°СЂС‚РѕС‡РєСѓ" РІРёРґР°:
      РўРёРї РїСЂРѕРєСЃРё: socks5
      РҐРѕСЃС‚: 109.104.153.100
      РџРѕСЂС‚: 10811
      Р›РѕРіРёРЅ: user
      РџР°СЂРѕР»СЊ: pass

    РўР°РєР¶Рµ РїРѕРЅРёРјР°РµС‚:
      type=...
      host=...
      port=...
      user=...
      pass=...
    """
    if not text:
        return None

    raw = text.strip()
    if not raw:
        return None

    # Р•СЃР»Рё Р±Р»РѕРє вЂ” СЌС‚Рѕ РїСЂРѕСЃС‚Рѕ РѕРґРЅР° СЃС‚СЂРѕРєР°, РїСѓСЃС‚СЊ РѕР±СЂР°Р±РѕС‚Р°РµС‚ parse_proxy_string
    if "\n" not in raw:
        return parse_proxy_string(raw)

    kv: Dict[str, str] = {}
    for line in raw.splitlines():
        l = line.strip()
        if not l:
            continue

        # РїРѕР·РІРѕР»СЏРµРј "РєР»СЋС‡: Р·РЅР°С‡РµРЅРёРµ" Рё "РєР»СЋС‡ = Р·РЅР°С‡РµРЅРёРµ"
        if ":" in l:
            k, v = l.split(":", 1)
        elif "=" in l:
            k, v = l.split("=", 1)
        else:
            # РµСЃР»Рё СЌС‚Рѕ РЅРµ key:value, РІРѕР·РјРѕР¶РЅРѕ СЌС‚Рѕ РѕР±С‹С‡РЅР°СЏ СЃС‚СЂРѕРєР° РїСЂРѕРєСЃРё вЂ” РїРѕРїСЂРѕР±СѓРµРј РїРѕР·Р¶Рµ
            continue

        k = (k or "").strip().lower()
        v = (v or "").strip()
        if not v:
            continue

        # РЅРѕСЂРјР°Р»РёР·СѓРµРј РєР»СЋС‡Рё
        if "С‚РёРї" in k or k in ("type", "scheme", "proto", "protocol"):
            kv["type"] = v
        elif "С…РѕСЃС‚" in k or k in ("host", "ip", "addr", "address"):
            kv["host"] = v
        elif "РїРѕСЂС‚" in k or k in ("port",):
            kv["port"] = v
        elif "Р»РѕРіРёРЅ" in k or "user" in k or k in ("username",):
            kv["username"] = v
        elif "РїР°СЂРѕР»СЊ" in k or "pass" in k:
            kv["password"] = v

    # Р•СЃР»Рё РїРѕС…РѕР¶Рµ РЅР° РєР°СЂС‚РѕС‡РєСѓ
    if "host" in kv and "port" in kv:
        host = kv.get("host", "").strip()
        if not _is_probable_host(host):
            return None
        try:
            port_i = int(str(kv.get("port", "")).strip())
        except Exception:
            return None

        return {
            "host": host,
            "port": port_i,
            "username": (kv.get("username") or "").strip() or None,
            "password": (kv.get("password") or "").strip() or None,
            "type": _normalize_proxy_type(kv.get("type")),
        }

    # РРЅР°С‡Рµ РїРѕРїСЂРѕР±СѓРµРј РЅР°Р№С‚Рё СЃС‚СЂРѕРєСѓ РїСЂРѕРєСЃРё РІРЅСѓС‚СЂРё Р±Р»РѕРєР° (РµСЃР»Рё С‡РµР»РѕРІРµРє РІСЃС‚Р°РІРёР» Р»РёС€РЅРёР№ С‚РµРєСЃС‚)
    for line in raw.splitlines():
        p = parse_proxy_string(line.strip())
        if p:
            return p

    return None
