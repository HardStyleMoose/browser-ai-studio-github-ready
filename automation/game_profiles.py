from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class GameProfile:
    key: str
    name: str
    genre: str
    strategy: str
    host_markers: tuple[str, ...] = ()
    title_markers: tuple[str, ...] = ()
    idle_clicker: bool = False
    autoplay_enabled: bool = True
    dom_priority_keywords: tuple[str, ...] = ()
    reward_keywords: tuple[str, ...] = ()
    progression_keywords: tuple[str, ...] = ()
    resource_keywords: tuple[str, ...] = ()
    social_keywords: tuple[str, ...] = ()
    purchase_avoid_keywords: tuple[str, ...] = ()
    primary_hotspots: tuple[tuple[float, float], ...] = ()
    reward_hotspots: tuple[tuple[float, float], ...] = ()
    upgrade_hotspots: tuple[tuple[float, float], ...] = ()
    dismiss_hotspots: tuple[tuple[float, float], ...] = ()
    ad_trigger_keywords: tuple[str, ...] = ()
    ad_close_keywords: tuple[str, ...] = ()
    burst_clicks: int = 2
    click_interval_steps: int = 1
    dom_scan_interval_steps: int = 4
    reward_scan_interval_steps: int = 8
    upgrade_scan_interval_steps: int = 6
    dismiss_scan_interval_steps: int = 12
    ad_scan_interval_steps: int = 14
    ad_watch_seconds: float = 12.0
    ad_watch_seconds_quick: float = 3.0
    quick_delay_s: float = 0.05
    normal_delay_s: float = 0.14
    gold_reward_scale: float = 0.01
    xp_reward_scale: float = 0.05
    level_reward_scale: float = 14.0
    loading_keywords: tuple[str, ...] = ()
    ready_keywords: tuple[str, ...] = ()


LEGENDS_OF_MUSHROOM_PROFILE = GameProfile(
    key="legends_of_mushroom",
    name="Legends of Mushroom",
    genre="Idle Clicker",
    strategy=(
        "Lamp-focused idle-click loop with guided claim, pass, rush, manor, crop, family, "
        "upgrade, and popup recovery sweeps tuned for lom.joynetgame.com."
    ),
    host_markers=("lom.joynetgame.com", "legendsofmushroom.com"),
    title_markers=("legends of mushroom", "mushroom"),
    idle_clicker=True,
    autoplay_enabled=True,
    dom_priority_keywords=(
        "claim",
        "collect",
        "reward",
        "free",
        "gift",
        "mail",
        "quest",
        "mission",
        "daily",
        "pass",
        "battle pass",
        "rush",
        "crop",
        "shop",
        "manor",
        "assistant",
        "harvest",
        "workteam",
        "family",
        "guild",
        "relic",
        "skill",
        "class",
        "soul",
        "soul stone",
        "crystal",
        "spinner",
        "mount",
        "awakening",
        "upgrade",
        "level",
        "boss",
        "challenge",
        "summon",
        "tap",
        "auto",
        "skip",
        "ok",
        "start",
        "play",
    ),
    reward_keywords=(
        "claim",
        "collect",
        "reward",
        "free",
        "gift",
        "bonus",
        "mail",
        "quest",
        "daily",
        "pass",
        "battle pass",
        "rush",
        "event",
        "harvest",
        "crop",
        "spinner",
    ),
    progression_keywords=(
        "campaign",
        "boss",
        "challenge",
        "battle",
        "stage",
        "relic",
        "skill",
        "class",
        "gear",
        "stat",
        "level",
        "awakening",
        "mount",
        "soul stone",
        "crystal",
    ),
    resource_keywords=("daily", "manor", "assistant", "harvest", "crop", "workteam", "spinner", "rush", "event", "mail", "quest"),
    social_keywords=("family", "guild", "team", "workteam", "friend", "chat"),
    purchase_avoid_keywords=(
        "buy",
        "purchase",
        "top up",
        "recharge",
        "bundle",
        "vip",
        "privilege",
        "pack",
        "limited offer",
        "special offer",
        "first purchase",
        "monthly card",
        "subscription",
        "diamond",
        "gem pack",
    ),
    primary_hotspots=((0.53, 0.84), (0.50, 0.84), (0.55, 0.82), (0.48, 0.82)),
    reward_hotspots=((0.88, 0.14), (0.93, 0.20), (0.84, 0.28), (0.91, 0.44), (0.08, 0.35), (0.23, 0.80), (0.28, 0.84)),
    upgrade_hotspots=((0.40, 0.91), (0.50, 0.91), (0.62, 0.91), (0.74, 0.91), (0.92, 0.76)),
    dismiss_hotspots=((0.95, 0.08), (0.91, 0.12), (0.84, 0.18)),
    ad_trigger_keywords=("watch", "video", "ad", "ads", "advert", "play ad"),
    ad_close_keywords=("close", "skip", "x", "done", "continue"),
    burst_clicks=2,
    click_interval_steps=2,
    dom_scan_interval_steps=3,
    reward_scan_interval_steps=4,
    upgrade_scan_interval_steps=5,
    dismiss_scan_interval_steps=8,
    ad_scan_interval_steps=14,
    ad_watch_seconds=18.0,
    ad_watch_seconds_quick=4.0,
    quick_delay_s=0.012,
    normal_delay_s=0.028,
    gold_reward_scale=0.015,
    xp_reward_scale=0.06,
    level_reward_scale=18.0,
    loading_keywords=(
        "loading",
        "config",
        "connecting",
        "logging in",
        "please wait",
        "starting",
        "initializing",
        "entering",
    ),
    ready_keywords=(
        "claim",
        "collect",
        "reward",
        "upgrade",
        "battle",
        "boss",
        "level",
    ),
)


GENERIC_BROWSER_PROFILE = GameProfile(
    key="generic_browser",
    name="Browser Game",
    genre="Browser Automation",
    strategy="Generic browser worker with lightweight capture, DOM scans, and saved self-play learning.",
    dom_priority_keywords=("play", "start", "ok", "next"),
    progression_keywords=("play", "start", "continue"),
    resource_keywords=("claim", "collect", "reward"),
    primary_hotspots=((0.50, 0.55),),
    reward_hotspots=((0.86, 0.18),),
    upgrade_hotspots=((0.80, 0.80),),
    dismiss_hotspots=((0.94, 0.08),),
    ad_trigger_keywords=("watch", "video", "ad"),
    ad_close_keywords=("close", "skip", "x"),
    loading_keywords=("loading", "config", "connecting", "please wait", "starting"),
    ready_keywords=("play", "start", "claim", "collect", "continue"),
)


GENERIC_DESKTOP_PROFILE = GameProfile(
    key="generic_desktop",
    name="Desktop Game",
    genre="Desktop Automation",
    strategy="Shared-window desktop worker that relies on the selected region and behavior graph.",
    autoplay_enabled=False,
)


def _normalized_host(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text if "://" in text else f"https://{text}")
    return (parsed.netloc or parsed.path or "").lower().replace("www.", "")


def _normalized_title(*values: str) -> str:
    return " ".join(str(value or "").strip().lower() for value in values if str(value or "").strip())


def resolve_game_profile(mode: str, browser_url: str = "", desktop_window_title: str = "", desktop_exe: str = "") -> GameProfile:
    mode_text = str(mode or "browser").lower()
    host = _normalized_host(browser_url)
    title_blob = _normalized_title(desktop_window_title, desktop_exe, Path(desktop_exe or "").name)

    for profile in (LEGENDS_OF_MUSHROOM_PROFILE,):
        if host and any(marker in host for marker in profile.host_markers):
            return profile
        if title_blob and any(marker in title_blob for marker in profile.title_markers):
            return profile

    if mode_text == "desktop":
        return GENERIC_DESKTOP_PROFILE
    return GENERIC_BROWSER_PROFILE


def format_game_display_name(mode: str, browser_url: str = "", desktop_window_title: str = "", desktop_exe: str = "") -> str:
    profile = resolve_game_profile(mode, browser_url=browser_url, desktop_window_title=desktop_window_title, desktop_exe=desktop_exe)
    if profile.key == "legends_of_mushroom":
        return "Legends of Mushroom (lom.joynetgame.com)"
    if str(mode or "").lower() == "desktop":
        title = str(desktop_window_title or "").strip()
        if title:
            return title
        exe_name = Path(str(desktop_exe or "").strip()).name
        return exe_name or profile.name
    host = _normalized_host(browser_url)
    return host or profile.name
