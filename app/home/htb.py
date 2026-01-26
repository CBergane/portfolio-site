import logging
import os
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
        "ownership": flags,
        "ranking": None,
        "points": None,
        "flags": flags,
        "machines": _safe_int(settings_obj.htb_boxes_owned),
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

    ownership = _safe_int(_pick(data, "ownership", "owns", "own_total"))
    if ownership is None:
        ownership = flags if flags is not None else machines

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
        "ownership": _safe_int(ownership),
        "ranking": _safe_int(ranking),
        "points": _safe_int(points),
        "flags": _safe_int(flags),
        "machines": _safe_int(machines),
        "bloods": _safe_int(bloods),
    }


def get_htb_profile(request) -> Dict[str, Any]:
    settings_obj = SocialMediaSettings.for_request(request)
    fallback = _build_fallback(settings_obj)

    token = os.getenv("HTB_TOKEN")
    user_id = os.getenv("HTB_USER_ID")
    if not token or not user_id:
        return fallback

    cache_key = f"htb:profile_basic:{user_id}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return cached

    url = f"{HTB_API_BASE}/user/profile/basic/{user_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, timeout=6)
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
    merged["source"] = "api"

    ttl = _safe_int(os.getenv("HTB_CACHE_TTL_SECONDS")) or DEFAULT_CACHE_TTL_SECONDS
    cache.set(cache_key, merged, ttl)
    return merged
