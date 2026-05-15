import logging
import os

import hashlib
from typing import Any, Dict, Optional

import requests
from django.core.cache import cache

from .models import SocialMediaSettings

logger = logging.getLogger(__name__)

HTB_API_BASE = "https://labs.hackthebox.com/api/v4"
DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60
FAILURE_CACHE_TTL_SECONDS = 10 * 60


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
    
def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick(data: Dict[str, Any], *keys: str) -> Optional[Any]:
    for key in keys:
        if key in data:
            return data.get(key)
    return None


def _build_fallback(settings_obj: SocialMediaSettings) -> Dict[str, Any]:
    user_owns = _safe_int(settings_obj.htb_user_owns)
    system_owns = _safe_int(settings_obj.htb_system_owns)
    flags = None
    if user_owns is not None or system_owns is not None:
        flags = (user_owns or 0) + (system_owns or 0)

    return {
        "rank": settings_obj.htb_rank or "Noob",
        "ownership": None,
        "ranking": None,
        "points": None,
        "flags": flags,
        "machines": system_owns if system_owns is not None else _safe_int(settings_obj.htb_boxes_owned),
        "bloods": _safe_int(settings_obj.htb_challenges),
        "source": "fallback",
    }


def _extract_profile_stats(payload: Dict[str, Any]) -> Dict[str, Any]:
    profile = payload.get("profile") if isinstance(payload, dict) else None
    data = profile if isinstance(profile, dict) else payload
    if not isinstance(data, dict):
        return {}

    rank = _pick(
        data,
        "rank",
        "rank_name",
        "rankname",
        "rankName",
    )
    ranking = _pick(data, "ranking", "rank_position", "rankPosition")
    points = _pick(data, "points", "score")

    user_owns = _safe_int(_pick(data, "user_owns", "user_owns_count", "user_owns_total"))
    system_owns = _safe_int(_pick(data, "system_owns", "system_owns_count", "system_owns_total"))

    flags = None
    if user_owns is not None or system_owns is not None:
        flags = (user_owns or 0) + (system_owns or 0)

    # I HTB "profile/basic" är "Machines" i praktiken system_owns i din UI
    machines = system_owns
    if machines is None:
        machines = _safe_int(
            _pick(
                data,
                "machine_owns",
                "machine_owns_total",
                "machines_owns",
                "boxes_owned",
                "box_owns",
            )
        )

    # HTB skickar rank_ownership (t.ex 6.15)
    ownership = _safe_float(_pick(data, "rank_ownership", "rankOwnership", "ownership"))

    bloods = _safe_int(_pick(data, "bloods", "bloods_total"))
    if bloods is None:
        user_bloods = _safe_int(_pick(data, "user_bloods", "user_bloods_total"))
        system_bloods = _safe_int(_pick(data, "system_bloods", "system_bloods_total"))
        challenge_bloods = _safe_int(_pick(data, "challenge_bloods", "challenge_bloods_total"))
        parts = [v for v in (user_bloods, system_bloods, challenge_bloods) if v is not None]
        if parts:
            bloods = sum(parts)

    return {
        "rank": rank,
        "ownership": ownership,
        "ranking": _safe_int(ranking),
        "points": _safe_int(points),
        "flags": _safe_int(flags),
        "machines": _safe_int(machines),
        "bloods": _safe_int(bloods),
    }
    

def _get_manual_xp_profile() -> Dict[str, Any]:
    xp_current = _safe_int(os.getenv("HTB_XP_CURRENT", "659"))
    xp_required = _safe_int(os.getenv("HTB_XP_REQUIRED", "1058"))

    xp_percent = None
    if xp_current is not None and xp_required:
        xp_percent = round((xp_current / xp_required) * 100, 1)
        xp_percent = max(0, min(xp_percent, 100))

    return {
        "profile_name": os.getenv("HTB_PROFILE_NAME", "CBergane"),
        "country_code": os.getenv("HTB_COUNTRY_CODE", "SE"),
        "xp_rank": os.getenv("HTB_XP_RANK", "Skilled"),
        "xp_level": os.getenv("HTB_XP_LEVEL", "43"),
        "xp_grade": os.getenv("HTB_XP_GRADE", "III"),
        "xp_current": os.getenv("HTB_XP_CURRENT", "659"),
        "xp_required": os.getenv("HTB_XP_REQUIRED", "1058"),
        "xp_percent": xp_percent,
        "weekly_streak": os.getenv("HTB_WEEKLY_STREAK", "11"),
        "weekly_xp": os.getenv("HTB_WEEKLY_XP", "200"),
        "weekly_xp_required": os.getenv("HTB_WEEKLY_XP_REQUIRED", "200"),
    }


def get_htb_profile(request) -> Dict[str, Any]:
    settings_obj = SocialMediaSettings.for_request(request)

    fallback = _build_fallback(settings_obj)
    fallback.update(_get_manual_xp_profile())
    fallback["legacy_rank"] = fallback.get("rank")

    token = os.getenv("HTB_TOKEN")
    user_id = os.getenv("HTB_USER_ID")
    if not token or not user_id:
        return fallback

    # Token-fingerprint i cache key så gamla fallback-cache inte lever kvar efter token-ändring
    token_fp = hashlib.sha256(token.encode("utf-8")).hexdigest()[:10]
    cache_key = f"htb:profile_basic:v2:{user_id}:{token_fp}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        cached.update(_get_manual_xp_profile())
        cached["legacy_rank"] = cached.get("legacy_rank") or cached.get("rank")
        return cached

    url = f"{HTB_API_BASE}/user/profile/basic/{user_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "curl/8.0.0",
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=20,
            proxies={"http": None, "https": None},
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        logger.warning("HTB profile fetch failed: %s", exc.__class__.__name__)
        cache.set(cache_key, fallback, FAILURE_CACHE_TTL_SECONDS)
        return fallback
    except ValueError:
        logger.warning("HTB profile fetch returned invalid JSON")
        cache.set(cache_key, fallback, FAILURE_CACHE_TTL_SECONDS)
        return fallback

    extracted = _extract_profile_stats(payload)
    if not extracted:
        cache.set(cache_key, fallback, FAILURE_CACHE_TTL_SECONDS)
        return fallback

    merged = {**fallback, **{k: v for k, v in extracted.items() if v is not None}}
    merged.update(_get_manual_xp_profile())
    merged["legacy_rank"] = merged.get("rank")
    merged["source"] = "api"
    
    ttl = _safe_int(os.getenv("HTB_CACHE_TTL_SECONDS")) or DEFAULT_CACHE_TTL_SECONDS
    
    cache.set(cache_key, merged, ttl)
    
    return merged
