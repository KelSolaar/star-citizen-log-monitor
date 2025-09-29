# /// script
# dependencies = [
#   "aiofiles==24.1.0",
#   "aiohttp==3.12.15",
#   "beautifulsoup4==4.14.0",
#   "click==8.3.0",
#   "pickledb==1.0",
#   "PySide6==6.9.2",
#   "pytz==2025.2",
#   "textual==2.1.2",
#   "tzlocal==5.2",
# ]
# ///

"""
Star Citizen Log Monitor
========================

An opinionated log monitor for `Star Citizen <https://robertsspaceindustries.com/>`__
with an emphasis put on extracting combat related data.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from pathlib import Path
from threading import Thread
from typing import Callable, List
from abc import ABC, abstractmethod

import aiofiles
import aiohttp
import click
import pytz
import tzlocal
from bs4 import BeautifulSoup
from pickledb import PickleDB
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, QTimer
from textual.app import App, ComposeResult
from textual.widgets import RichLog
from textual.worker import Worker

__author__ = "Thomas Mansencal"
__copyright__ = "Copyright 2025 Thomas Mansencal"
__license__ = "BSD-3-Clause - https://opensource.org/licenses/BSD-3-Clause"
__maintainer__ = "Thomas Mansencal"
__status__ = "Production"

__application__ = "Star Citizen Log Monitor"

__version__ = "0.10.0"

__all__ = [
    "LOCAL_TIMEZONE",
    "PATTERN_TIMESTAMP_RAW",
    "PATTERN_TIMESTAMP_BEAUTIFIED",
    "PATTERN_NOTICE",
    "HIGHLIGHT_PATTERNS",
    "COLOUR_MAPPING",
    "PATH_EXCEPTION_LOG",
    "CACHE_ORGANIZATIONS",
    "TTL_ORGANIZATION",
    "Entity",
    "ParsedEvent",
    "catch_exception",
    "fetch_page",
    "extract_organization_name",
    "beautify_timestamp",
    "beautify_entity_name",
    "Logger",
    "OverlayWindow",
    "StarCitizenLogMonitorApp",
    "parse_event_on_client_spawned",
    "parse_event_connect_started",
    "parse_event_on_client_connected",
    "parse_event_request_quit_lobby",
    "parse_event_actor_death",
    "parse_event_vehicle_destruction",
    "parse_event_requesting_transition",
    "parse_event_actor_state_corpse",
    "parse_event_actor_stall",
    "parse_event_lost_spawn_reservation",
    "EVENT_PARSERS",
    "main",
]

LOCAL_TIMEZONE = tzlocal.get_localzone()

PATTERN_TIMESTAMP_RAW = r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z)"
PATTERN_TIMESTAMP_BEAUTIFIED = (
    r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:AM|PM))"
)

PATTERN_NOTICE = "<" + PATTERN_TIMESTAMP_RAW + ">" + r" \[Notice]\ "

# Shared highlighting patterns and colors
HIGHLIGHT_PATTERNS = [
    (r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:AM|PM))", "timestamp"),
    # Basic Events
    (r"(?P<clientspawned>\[Client Spawned\])", "clientspawned"),
    (r"(?P<connectstarted>\[Connect Started\])", "connectstarted"),
    (r"(?P<clientconnected>\[Client Connected\])", "clientconnected"),
    # Request Quit Lobby
    (r"(?P<requestquitlobby>\[Request Quit Lobby\])", "requestquitlobby"),
    # Requesting Transition
    (r"(?P<requestingtransition>\[Requesting Transition\])", "requestingtransition"),
    (
        r"(?P<classifier>From): (?P<fromsystem>[\w_-]+) \((?P<fromzone>[\w_-]+)\),",
        "classifier",
        "fromsystem",
        "fromzone",
    ),
    (
        r"(?P<classifier>To): (?P<tosystem>[\w_-]+) \((?P<tozone>[\w_-]+)\)",
        "classifier",
        "tosystem",
        "tozone",
    ),
    # Common fields
    (r"(?P<classifier>Zone): (?P<zone>[\w_-]+),", "classifier", "zone"),
    # Actor Death
    (r"(?P<actordeath>\[Actor Death\])", "actordeath"),
    (
        r"(?P<classifier>Victim): (?P<victim>[\w_-]+(?:\s+\([\w_-]+\))?),",
        "classifier",
        "victim",
    ),
    (
        r"(?P<classifier>Killer): (?P<killer>[\w_-]+(?:\s+\([\w_-]+\))?)(?:,|$)",
        "classifier",
        "killer",
    ),
    (r"(?P<classifier>Weapon): (?P<weapon>[\w_-]+)", "classifier", "weapon"),
    # Vehicle Destruction
    (r"(?P<vehicledestruction>\[Vehicle Destruction\])", "vehicledestruction"),
    (r"(?P<classifier>Vehicle): (?P<vehicle>[\w_-]+),", "classifier", "vehicle"),
    (
        r"(?P<classifier>Driver): (?P<driver>[\w_-]+(?:\s+\([\w_-]+\))?),",
        "classifier",
        "driver",
    ),
    (
        r"(?P<classifier>Caused By): (?P<causer>[\w_-]+(?:\s+\([\w_-]+\))?),",
        "classifier",
        "causer",
    ),
    (r"(?P<classifier>Cause): (?P<cause>[\w_-]+),", "classifier", "cause"),
    # Actor State Corpse
    (r"(?P<corpse>\[Corpse\])", "corpse"),
    # Actor Stall
    (r"(?P<actorstall>\[Actor Stall\])", "actorstall"),
    # Common player pattern (with optional comma)
    (
        r"(?P<classifier>Player): (?P<player>[\w_-]+(?:\s+\([\w_-]+\))?)(?:,|$)?",
        "classifier",
        "player",
    ),
    # Spawn Lost
    (r"(?P<spawnlost>\[Spawn Lost\])", "spawnlost"),
]

COLOUR_MAPPING = {
    "timestamp": "#1E90FF",  # DodgerBlue
    "classifier": "white",  # Bold white
    "clientspawned": "#228B22",  # ForestGreen
    "connectstarted": "#228B22",  # ForestGreen
    "clientconnected": "#228B22",  # ForestGreen
    "requestquitlobby": "#FF8C00",  # Orange1
    "requester": "#DC143C",  # Crimson
    "requestingtransition": "#9370DB",  # MediumPurple
    "fromsystem": "#228B22",  # ForestGreen
    "fromzone": "#228B22",  # ForestGreen
    "tosystem": "#228B22",  # ForestGreen
    "tozone": "#228B22",  # ForestGreen
    "zone": "#228B22",  # ForestGreen
    "actordeath": "#DC143C",  # Crimson
    "victim": "#FF69B4",  # HotPink
    "killer": "#DC143C",  # Crimson
    "weapon": "#A52A2A",  # Brown
    "vehicledestruction": "#FF8C00",  # Orange1
    "vehicle": "#FF69B4",  # HotPink
    "driver": "#FF69B4",  # HotPink
    "causer": "#DC143C",  # Crimson
    "cause": "#A52A2A",  # Brown
    "corpse": "#DC143C",  # Crimson
    "player": "#FF69B4",  # HotPink
    "actorstall": "#FF8C00",  # Orange1
    "spawnlost": "#EEEEEE",  # White
    "number": "#1E90FF",  # DodgerBlue
    "spawnpoint": "#9370DB",  # MediumPurple
    "error": "#DC143C",  # Crimson for exceptions/errors
    "default": "#EEEEEE",  # Default white
}

PATH_EXCEPTION_LOG = Path(__file__).parent / ".exceptions"


class Entity(ABC):
    """Abstract base class for all entities in parsed events."""

    def __init__(self, text: str, color: str = COLOUR_MAPPING["default"]):
        self.text = text
        self.color = color

    @abstractmethod
    def render_textual(self) -> str:
        """Render this entity for Textual (Rich markup)."""
        pass

    @abstractmethod
    def render_overlay(self) -> str:
        """Render this entity for Qt overlay (HTML)."""
        pass


class TextEntity(Entity):
    """Plain text entity with color."""

    def render_textual(self) -> str:
        return f"[{self.color}]{self.text}[/{self.color}]"

    def render_overlay(self) -> str:
        return f'<span style="color: {self.color};">{self.text}</span>'


class PlayerEntity(Entity):
    """Player entity that can have organization and links."""

    def __init__(
        self, text: str, color: str = COLOUR_MAPPING["player"], org_name: str = None
    ):
        super().__init__(text, color)
        self.org_name = org_name

    @classmethod
    async def __async_init__(cls, raw_name: str, color: str = COLOUR_MAPPING["player"]):
        """Create PlayerEntity with beautified name and organization."""

        beautified_name = beautify_entity_name(raw_name)
        org_name = await extract_organization_name(beautified_name)
        return cls(beautified_name, color, org_name)

    def render_textual(self) -> str:
        if should_create_player_link(self.text):
            result = f"[link=https://robertsspaceindustries.com/citizens/{self.text}][{self.color}]{self.text}[/{self.color}][/link]"
        else:
            result = f"[{self.color}]{self.text}[/{self.color}]"

        if self.org_name:
            result += f"[{self.color}] ([link=https://robertsspaceindustries.com/orgs/{self.org_name}]{self.org_name}[/link])[/{self.color}]"

        return result

    def render_overlay(self) -> str:
        if should_create_player_link(self.text):
            result = f'<a href="https://robertsspaceindustries.com/citizens/{self.text}" style="color: {self.color}; text-decoration: underline;">{self.text}</a>'
        else:
            result = f'<span style="color: {self.color};">{self.text}</span>'

        if self.org_name:
            org_link = f'<a href="https://robertsspaceindustries.com/orgs/{self.org_name}" style="color: {self.color}; text-decoration: underline;">{self.org_name}</a>'
            result = f'<span style="color: {self.color};">{result} ({org_link})</span>'

        return result


class ZoneEntity(Entity):
    """Zone/location entity."""

    def __init__(self, raw_name: str, color: str = COLOUR_MAPPING["zone"]):
        super().__init__(beautify_entity_name(raw_name), color)

    def render_textual(self) -> str:
        return f"[{self.color}]{self.text}[/{self.color}]"

    def render_overlay(self) -> str:
        return f'<span style="color: {self.color};">{self.text}</span>'


class WeaponEntity(Entity):
    """Weapon entity."""

    def __init__(self, raw_name: str, color: str = COLOUR_MAPPING["weapon"]):
        super().__init__(beautify_entity_name(raw_name), color)

    def render_textual(self) -> str:
        return f"[{self.color}]{self.text}[/{self.color}]"

    def render_overlay(self) -> str:
        return f'<span style="color: {self.color};">{self.text}</span>'


class VehicleEntity(Entity):
    """Vehicle entity."""

    def __init__(self, text: str, color: str = COLOUR_MAPPING["vehicle"]):
        super().__init__(text, color)

    def render_textual(self) -> str:
        return f"[{self.color}]{self.text}[/{self.color}]"

    def render_overlay(self) -> str:
        return f'<span style="color: {self.color};">{self.text}</span>'


class CauseEntity(Entity):
    """Cause/reason entity."""

    def __init__(self, raw_name: str, color: str = COLOUR_MAPPING["cause"]):
        super().__init__(beautify_entity_name(raw_name), color)

    def render_textual(self) -> str:
        return f"[{self.color}]{self.text}[/{self.color}]"

    def render_overlay(self) -> str:
        return f'<span style="color: {self.color};">{self.text}</span>'


class SystemEntity(Entity):
    """System entity."""

    def __init__(self, raw_name: str, color: str = COLOUR_MAPPING["zone"]):
        super().__init__(beautify_entity_name(raw_name), color)

    def render_textual(self) -> str:
        return f"[{self.color}]{self.text}[/{self.color}]"

    def render_overlay(self) -> str:
        return f'<span style="color: {self.color};">{self.text}</span>'


class NumberEntity(Entity):
    """Numeric value entity."""

    def __init__(self, value: str, color: str = COLOUR_MAPPING["number"]):
        super().__init__(value, color)

    def render_textual(self) -> str:
        return f"[{self.color}]{self.text}[/{self.color}]"

    def render_overlay(self) -> str:
        return f'<span style="color: {self.color};">{self.text}</span>'


class SpawnpointEntity(Entity):
    """Spawnpoint entity."""

    def __init__(self, raw_name: str, color: str = COLOUR_MAPPING["spawnpoint"]):
        super().__init__(beautify_entity_name(raw_name), color)

    def render_textual(self) -> str:
        return f"[{self.color}]{self.text}[/{self.color}]"

    def render_overlay(self) -> str:
        return f'<span style="color: {self.color};">{self.text}</span>'


class TimestampEntity(Entity):
    """Timestamp entity."""

    def __init__(self, raw_timestamp: str, color: str = COLOUR_MAPPING["timestamp"]):
        super().__init__(beautify_timestamp(raw_timestamp), color)

    def render_textual(self) -> str:
        return f"[{self.color}]{self.text}[/{self.color}]"

    def render_overlay(self) -> str:
        return f'<span style="color: {self.color};">{self.text}</span>'


class CategoryEntity(Entity):
    """Event category entity."""

    def __init__(self, text: str, color: str = None):
        # Map category text to appropriate colors
        if color is None:
            category_map = {
                "Client Spawned": COLOUR_MAPPING["clientspawned"],
                "Connect Started": COLOUR_MAPPING["connectstarted"],
                "Client Connected": COLOUR_MAPPING["clientconnected"],
                "Request Quit Lobby": COLOUR_MAPPING["requestquitlobby"],
                "Requesting Transition": COLOUR_MAPPING["requestingtransition"],
                "Actor Death": COLOUR_MAPPING["actordeath"],
                "Vehicle Destruction": COLOUR_MAPPING["vehicledestruction"],
                "Corpse": COLOUR_MAPPING["corpse"],
                "Actor Stall": COLOUR_MAPPING["actorstall"],
                "Spawn Lost": COLOUR_MAPPING["spawnlost"],
            }
            color = category_map.get(text, COLOUR_MAPPING["default"])
        super().__init__(text, color)

    def render_textual(self) -> str:
        return f"[{self.color}][{self.text}][/{self.color}]"

    def render_overlay(self) -> str:
        return f'<span style="color: {self.color};">[{self.text}]</span>'


@dataclass
class ParsedEvent:
    """Represents a parsed event with entities."""

    entities: List[
        Entity
    ]  # All components: timestamp, category, players, zones, weapons, etc.

    def render_textual(self) -> str:
        """Render this ParsedEvent for Textual console."""

        return "".join(entity.render_textual() for entity in self.entities)

    def render_overlay(self) -> str:
        """Render this ParsedEvent for Qt overlay."""

        return "".join(entity.render_overlay() for entity in self.entities)


def catch_exception(function: Callable) -> Callable:
    """Catch exceptions and return as ParsedEvent objects."""

    @wraps(function)
    async def wrapper(*args, **kwargs):
        try:
            return await function(*args, **kwargs)
        except Exception:
            tb = traceback.format_exc()

            # Write exception to file for debugging
            with open(PATH_EXCEPTION_LOG, "a") as exception_log:
                exception_log.write(
                    f"{datetime.now().strftime('%H:%M:%S')}: {function.__name__}: ARGS={args}: {tb}\n"
                )

            # Return a ParsedEvent for the exception instead of a string
            return ParsedEvent(
                entities=[
                    TextEntity(f"Exception in {function.__name__}: {tb}", COLOUR_MAPPING["error"])
                ]
            )

    return wrapper


async def fetch_page(session: aiohttp.ClientSession, url: str) -> tuple[int, str]:
    """Fetch a web page and return status code and content."""

    async with session.get(url) as response:
        return response.status, await response.text()


CACHE_ORGANIZATIONS = PickleDB(Path(__file__).parent / ".organizations")

TTL_ORGANIZATION = 3600 * 24 * 72  # 3 Days

_ENABLE_ORGANIZATION_FETCHING = True


async def extract_organization_name(player: str) -> str | None:
    """Extract organization name for a player from RSI website."""

    if not _ENABLE_ORGANIZATION_FETCHING:
        return None

    if player in CACHE_ORGANIZATIONS.all():
        data = CACHE_ORGANIZATIONS.get(player)

        if time.time() < data["expiration"]:
            return data["organization"]

    url = f"https://robertsspaceindustries.com/en/citizens/{player}"
    async with aiohttp.ClientSession() as session:
        status, html_content = await fetch_page(session, url)

        # If page not found (404), mark as not a player
        if status == 404:
            CACHE_ORGANIZATIONS.set(
                player,
                {
                    "organization": None,
                    "is_player": False,
                    "expiration": time.time() + TTL_ORGANIZATION,
                },
            )
            CACHE_ORGANIZATIONS.save()
            return None

        soup = BeautifulSoup(html_content, "html.parser")
        sid = soup.find(text="Spectrum Identification (SID)")
        if sid is None:
            # Player exists (200 status) but has no organization section
            CACHE_ORGANIZATIONS.set(
                player,
                {
                    "organization": None,
                    "is_player": True,
                    "expiration": time.time() + TTL_ORGANIZATION,
                },
            )

            CACHE_ORGANIZATIONS.save()

            return None

        organization = sid.find_next().text.strip()

        CACHE_ORGANIZATIONS.set(
            player,
            {
                "organization": organization,
                "is_player": True,
                "expiration": time.time() + TTL_ORGANIZATION,
            },
        )

        CACHE_ORGANIZATIONS.save()

        return organization


class Logger(RichLog):
    """Custom logger extending RichLog."""

    def flush(self) -> None:
        pass


def beautify_timestamp(timestamp: str) -> str:
    """Convert UTC timestamp to local timezone."""

    utc_timestamp = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    utc_timestamp = utc_timestamp.replace(tzinfo=pytz.UTC)

    local_timestamp = utc_timestamp.astimezone(LOCAL_TIMEZONE)

    return local_timestamp.strftime("%Y-%m-%d %I:%M:%S%p")


def beautify_entity_name(name: str) -> str:
    """Remove numeric suffixes from entity names."""

    if match := re.match(r"([\w_-]+)_\d{10,}$", name):
        return match.group(1)

    return name


def should_create_player_link(player: str) -> bool:
    """Check if player should have clickable link."""

    if _ENABLE_ORGANIZATION_FETCHING and player in CACHE_ORGANIZATIONS.all():
        data = CACHE_ORGANIZATIONS.get(player)
        if time.time() < data["expiration"]:
            return data.get("is_player", True)

    if not _ENABLE_ORGANIZATION_FETCHING:
        return False  # No links when fetching is disabled

    # Player not yet validated, don't create link
    return False


@catch_exception
async def parse_event_on_client_spawned(log_line: str) -> ParsedEvent | None:
    pattern = re.compile(
        "<"
        + PATTERN_TIMESTAMP_RAW
        + "> "
        + r"\[CSessionManager::OnClientSpawned\] Spawned!"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        entities = [
            TimestampEntity(data["timestamp"]),
            TextEntity(" "),
            CategoryEntity("Client Spawned"),
        ]

        return ParsedEvent(entities=entities)

    return None


@catch_exception
async def parse_event_connect_started(log_line: str) -> ParsedEvent | None:
    pattern = re.compile(
        "<"
        + PATTERN_TIMESTAMP_RAW
        + "> "
        + r"\[CSessionManager::ConnectCmd\] Connect started!"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        entities = [
            TimestampEntity(data["timestamp"]),
            TextEntity(" "),
            CategoryEntity("Connect Started"),
        ]

        return ParsedEvent(entities=entities)

    return None


@catch_exception
async def parse_event_on_client_connected(log_line: str) -> ParsedEvent | None:
    pattern = re.compile(
        "<"
        + PATTERN_TIMESTAMP_RAW
        + "> "
        + r"\[CSessionManager::OnClientConnected\] Connected!"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return ParsedEvent(
            entities=[
                TimestampEntity(data["timestamp"]),
                TextEntity(" "),
                CategoryEntity("Client Connected"),
            ]
        )

    return None


@catch_exception
async def parse_event_request_quit_lobby(log_line: str) -> ParsedEvent | None:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<\[EALobby\] EALobbyQuit> \[EALobby\]\[CEALobby::RequestQuitLobby\] (?P<requester>[\w_-]+) Requesting QuitLobby"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return ParsedEvent(
            entities=[
                TimestampEntity(data["timestamp"]),
                TextEntity(" "),
                CategoryEntity("Request Quit Lobby"),
                TextEntity(" "),
                TextEntity("Requester: "),
                await PlayerEntity.__async_init__(
                    data["requester"], COLOUR_MAPPING["requester"]
                ),
            ]
        )

    return None


@catch_exception
async def parse_event_actor_death(log_line: str) -> ParsedEvent | None:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<Actor Death> CActor::Kill: '(?P<victim>[\w_-]+)' \[\d+\] in zone '(?P<zone>[\w_-]+)' killed by '(?P<killer>[\w_-]+)' \[\d+\] using '(?P<weapon>[\w_-]+)' \[Class (?P<weapon_class>[\w_-]+)\] with damage type '(?P<damage_type>[\w_-]+)' from direction x: (?P<direction_x>[-\d.]+), y: (?P<direction_y>[-\d.]+), z: (?P<direction_z>[-\d.]+)"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return ParsedEvent(
            entities=[
                TimestampEntity(data["timestamp"]),
                TextEntity(" "),
                CategoryEntity("Actor Death"),
                TextEntity(" "),
                TextEntity("Victim: "),
                await PlayerEntity.__async_init__(
                    data["victim"], COLOUR_MAPPING["victim"]
                ),
                TextEntity(", "),
                TextEntity("Killer: "),
                await PlayerEntity.__async_init__(
                    data["killer"], COLOUR_MAPPING["killer"]
                ),
                TextEntity(", "),
                TextEntity("Zone: "),
                ZoneEntity(data["zone"]),
                TextEntity(", "),
                TextEntity("Weapon: "),
                WeaponEntity(data["weapon"]),
            ]
        )

    return None


@catch_exception
async def parse_event_vehicle_destruction(log_line: str) -> ParsedEvent | None:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<Vehicle Destruction> CVehicle::OnAdvanceDestroyLevel: Vehicle '(?P<vehicle_name>[\w_-]+)' \[(?P<vehicle_id>\d+)\] in zone '(?P<zone>[\w_-]+)' \[pos x: (?P<pos_x>[-\d.]+), y: (?P<pos_y>[-\d.]+), z: (?P<pos_z>[-\d.]+) vel x: (?P<vel_x>[-\d.]+), y: (?P<vel_y>[-\d.]+), z: (?P<vel_z>[-\d.]+)\] driven by '(?P<driver>[\w_-]+)' \[(?P<driver_id>\d+)\] advanced from destroy level (?P<destroy_level_from>\d+) to (?P<destroy_level_to>\d+) caused by '(?P<causer>[\w_-]+)' \[(?P<causer_id>\d+)\] with '(?P<cause>[^\']+)'"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return ParsedEvent(
            entities=[
                TimestampEntity(data["timestamp"]),
                TextEntity(" "),
                CategoryEntity("Vehicle Destruction"),
                TextEntity(" "),
                TextEntity("Vehicle: "),
                VehicleEntity(data["vehicle_name"]),
                TextEntity(", "),
                TextEntity("Driver: "),
                await PlayerEntity.__async_init__(
                    data["driver"], COLOUR_MAPPING["driver"]
                ),
                TextEntity(", "),
                TextEntity("Caused By: "),
                await PlayerEntity.__async_init__(
                    data["causer"], COLOUR_MAPPING["causer"]
                ),
                TextEntity(", "),
                TextEntity("Cause: "),
                CauseEntity(data["cause"]),
                TextEntity(", "),
                TextEntity("Zone: "),
                ZoneEntity(data["zone"]),
            ]
        )

    return None


@catch_exception
async def parse_event_requesting_transition(log_line: str) -> ParsedEvent | None:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<Requesting Transition> (?P<component>[^\|]+) \| (?P<status>[^\|]+) \| (?P<current_system>[^\|]+) \| (?P<host>[\w_-]+) \[(?P<host_id>\d+)\] \| Transitioning from zone (?P<from_zone>[\w_-]+) in (?P<from_system>[\w_-]+) to zone (?P<to_zone>[\w_-]+) in (?P<to_system>[\w_-]+) \[(?P<team>[\w_-]+)\]\[(?P<category>\w+)\]"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return ParsedEvent(
            entities=[
                TimestampEntity(data["timestamp"]),
                TextEntity(" "),
                CategoryEntity("Requesting Transition"),
                TextEntity(" "),
                TextEntity("From: "),
                SystemEntity(data["from_system"]),
                TextEntity(" ("),
                ZoneEntity(data["from_zone"]),
                TextEntity("), "),
                TextEntity("To: "),
                SystemEntity(data["to_system"]),
                TextEntity(" ("),
                ZoneEntity(data["to_zone"]),
                TextEntity(")"),
            ]
        )

    return None


@catch_exception
async def parse_event_actor_state_corpse(log_line: str) -> ParsedEvent | None:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<\[ActorState\] Corpse> \[ACTOR STATE\]\[SSCActorStateCVars::LogCorpse\] Player '(?P<player>[\w_-]+)' <remote client>: Running corpsify for corpse\. \[Team_ActorFeatures\]\[Actor\]"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return ParsedEvent(
            entities=[
                TimestampEntity(data["timestamp"]),
                TextEntity(" "),
                CategoryEntity("Corpse"),
                TextEntity(" "),
                TextEntity("Player: "),
                await PlayerEntity.__async_init__(
                    data["player"], COLOUR_MAPPING["player"]
                ),
            ]
        )

    return None


@catch_exception
async def parse_event_actor_stall(log_line: str) -> ParsedEvent | None:
    pattern = re.compile(
        r"<(?P<timestamp>[\d\-T:.Z]+)> \[Notice\] <Actor stall> Actor stall detected, Player: (?P<player>[\w_-]+), Type: (?P<type>\w+), Length: (?P<length>[\d.]+)\. \[Team_ActorTech\]\[Actor\]"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return ParsedEvent(
            entities=[
                TimestampEntity(data["timestamp"]),
                TextEntity(" "),
                CategoryEntity("Actor Stall"),
                TextEntity(" "),
                TextEntity("Player: "),
                await PlayerEntity.__async_init__(
                    data["player"], COLOUR_MAPPING["player"]
                ),
                TextEntity(", "),
                TextEntity("Length: "),
                NumberEntity(str(round(float(data["length"]), 1))),
            ]
        )

    return None


@catch_exception
async def parse_event_lost_spawn_reservation(log_line: str) -> ParsedEvent | None:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<Spawn Flow> CSCPlayerPUSpawningComponent::UnregisterFromExternalSystems: Player '(?P<player>[\w_-]+)' \[(?P<player_id>\d+)\] lost reservation for spawnpoint (?P<spawnpoint>\w+) \[(?P<spawnpoint_id>\d+)\] at location (?P<location>\d+) \[Team_ActorFeatures\]\[Gamerules\]"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return ParsedEvent(
            entities=[
                TimestampEntity(data["timestamp"]),
                TextEntity(" "),
                CategoryEntity("Spawn Lost"),
                TextEntity(" "),
                TextEntity("Player: "),
                await PlayerEntity.__async_init__(
                    data["player"], COLOUR_MAPPING["player"]
                ),
            ]
        )

    return None


EVENT_PARSERS = {
    "client-spawned": parse_event_on_client_spawned,
    "connect-started": parse_event_connect_started,
    "client-connected": parse_event_on_client_connected,
    "request-quit-lobby": parse_event_request_quit_lobby,
    "actor-death": parse_event_actor_death,
    "vehicle-destruction": parse_event_vehicle_destruction,
    "requesting-transition": parse_event_requesting_transition,
    "actor-state-corpse": parse_event_actor_state_corpse,
    "actor-stall": parse_event_actor_stall,
    "lost-spawn-reservation": parse_event_lost_spawn_reservation,
}


class OverlayWindow(QWidget):
    """Transparent overlay window for displaying log events."""

    def __init__(self, max_lines: int = 3, display: int = 0, font_size: int = 16):
        super().__init__()
        self.max_lines = max_lines
        self.display = display
        self.font_size = font_size
        self.lines = deque(maxlen=max_lines)
        self.running = False

        self.drag_start_position = None
        self.drag_offset = None

        self.fixed_height = self.max_lines * (self.font_size + 5) + 40

        self.setup_widget()

    def setup_widget(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)

        self.setAttribute(Qt.WA_TranslucentBackground)

        self.setStyleSheet("""
            QWidget {
                border-top: 3px solid rgba(255, 255, 255, 0.4);
                background-color: transparent;
            }
        """)

        main_layout = QVBoxLayout()
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.drag_indicator = QLabel()
        self.drag_indicator.setFixedHeight(4)
        self.drag_indicator.setStyleSheet("""
            QLabel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(30, 144, 255, 0.0),
                    stop:0.5 rgba(30, 144, 255, 0.75),
                    stop:1 rgba(30, 144, 255, 0.0));
                border: none;
            }
        """)

        self.label = QLabel()
        self.label.setTextFormat(Qt.RichText)
        self.label.setOpenExternalLinks(True)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(f"""
            QLabel {{
                background-color: transparent;
                color: white;
                font-family: Consolas, Terminal, monospace;
                font-size: {self.font_size}px;
                font-weight: bold;
                border: none;
            }}
            QLabel a {{
                text-decoration: underline;
            }}
        """)

        main_layout.addWidget(self.drag_indicator)
        main_layout.addWidget(self.label)
        self.setLayout(main_layout)

        self.stay_on_top_timer = QTimer()
        self.stay_on_top_timer.timeout.connect(lambda: self.raise_() if self.running else None)
        self.stay_on_top_timer.start(1000)

    def start(self):
        self.running = True
        self.setWindowTitle(f"[ {__application__} - Overlay - {__version__} ]")

        if application := QApplication.instance():
            screens = application.screens()

            if self.display < len(screens):
                target_screen = screens[self.display]
            else:
                target_screen = application.primaryScreen()

            screen_geometry = target_screen.geometry()

            window_width = int(screen_geometry.width() * 2 / 3)

            self.setFixedSize(window_width, self.fixed_height)

            x = screen_geometry.x() + int((screen_geometry.width() - window_width) / 2)
            y = screen_geometry.y()

            self.move(x, y)

        self.show()

    def write(self, line: str):
        """Write line to overlay."""
        if not self.running:
            return

        self.lines.append(line)
        html_content = "<br>".join(self.lines)
        self.label.setText(html_content)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.globalPos()
            self.drag_offset = event.pos()

    def mouseMoveEvent(self, event):
        if (
            self.drag_start_position is not None
            and self.drag_offset is not None
            and event.buttons() == Qt.LeftButton
        ):
            new_pos = event.globalPos() - self.drag_offset
            self.move(new_pos)

    def mouseReleaseEvent(self, event):
        self.drag_start_position = None
        self.drag_offset = None


class StarCitizenLogMonitorApp(App):
    """Main Textual application for log monitoring."""

    def __init__(
        self,
        log_file_path: str,
        show_parsed_events_only: bool = True,
        event_filters: tuple[str, ...] = (),
        overlay_event_filters: tuple[str, ...] = (),
        overlay_window=None,
    ):
        super().__init__()

        self.log_file_path = log_file_path
        self.show_parsed_events_only = show_parsed_events_only
        self.event_filters = (
            set(event_filters) if event_filters else set(EVENT_PARSERS.keys())
        )
        self.overlay_event_filters = (
            set(overlay_event_filters) if overlay_event_filters else self.event_filters
        )
        self.overlay_window = overlay_window

        self.log_file_size = os.path.getsize(self.log_file_path)

        self.logger = Logger(highlight=False, markup=True)

        self.worker: Worker | None = None

    def compose(self) -> ComposeResult:
        yield self.logger

    def on_mount(self):
        # Set screen background programmatically
        self.screen.styles.background = "#111111"
        self.logger.styles.background = "#111111"

        self.logger.write(f"[ {__application__} - {__version__} ]")
        self.worker = self.run_worker(self.monitor())

    async def process_line(self, line: str):
        if not self.show_parsed_events_only:
            self.logger.write(line)
            if self.overlay_window:
                self.overlay_window.write(line)

        for event_key, event_parser in EVENT_PARSERS.items():
            if parsed_event := await event_parser(line):
                if event_key in self.event_filters:
                    self.logger.write(parsed_event.render_textual())

                if self.overlay_window and event_key in self.overlay_event_filters:
                    self.overlay_window.write(parsed_event.render_overlay())

                if event_key in self.event_filters or (
                    self.overlay_window and event_key in self.overlay_event_filters
                ):
                    return

    async def monitor(self):
        # External loop reloading the log file when the game restarts.
        while True:
            self.log_file_size = os.path.getsize(self.log_file_path)

            try:
                async with aiofiles.open(
                    self.log_file_path, mode="r", encoding="ISO-8859-2"
                ) as file:
                    for line in await file.readlines():
                        await self.process_line(line)

                    while True:
                        # Checking log file size, lower size implies that the game restarted,
                        # thus, the log file will need to be reloaded.
                        size = os.path.getsize(self.log_file_path)

                        if size < self.log_file_size:
                            self.logger.write(
                                f"[ {__application__} - {__version__} - Restarting... ]"
                            )
                            break

                        self.log_file_size = size

                        line = await file.readline()

                        if not line:
                            await asyncio.sleep(0.05)

                            continue

                        await self.process_line(line)
            except Exception as error:
                with open(PATH_EXCEPTION_LOG, "a") as exception_log:
                    exception_log.write(
                        f"{datetime.now().strftime('%H:%M:%S')}: {error}\n"
                    )

                await self.process_line(str(error))


@click.command()
@click.option(
    "--log-file-path",
    default=r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Game.log",
    help="Log file path",
)
@click.option(
    "--enable-organization-fetching",
    default=True,
    help="Whether to enable player organization fetching",
)
@click.option(
    "--show-parsed-events-only",
    default=True,
    help="Whether to only show the parsed events",
)
@click.option(
    "--event",
    multiple=True,
    help="Event types to include (if not specified, all events are included)",
)
@click.option(
    "--overlay-event",
    multiple=True,
    help="Event types to include in overlay (if not specified, uses --event filter)",
)
@click.option(
    "--overlay",
    is_flag=True,
    help="Enable overlay mode with transparent window",
)
@click.option(
    "--overlay-lines",
    default=3,
    help="Number of lines to show in overlay (default: 3)",
)
@click.option(
    "--overlay-display",
    default=0,
    help="Display number to show overlay on (default: 0)",
)
@click.option(
    "--overlay-font-size",
    default=16,
    help="Font size for overlay text (default: 16)",
)
def main(
    log_file_path: str,
    enable_organization_fetching: bool,
    show_parsed_events_only: bool,
    event: tuple[str, ...],
    overlay_event: tuple[str, ...],
    overlay: bool,
    overlay_lines: int,
    overlay_display: int,
    overlay_font_size: int,
) -> None:
    global _ENABLE_ORGANIZATION_FETCHING

    _ENABLE_ORGANIZATION_FETCHING = enable_organization_fetching

    if overlay:
        application = QApplication([])

        overlay_window = OverlayWindow(
            overlay_lines, overlay_display, overlay_font_size
        )
        overlay_window.start()

        overlay_window.write(f"[ {__application__} - Overlay - {__version__} ]")

        app = StarCitizenLogMonitorApp(
            log_file_path, show_parsed_events_only, event, overlay_event, overlay_window
        )
        app_thread = Thread(target=app.run, daemon=True)
        app_thread.start()

        try:
            application.exec()
        finally:
            overlay_window.stop()
    else:
        app = StarCitizenLogMonitorApp(
            log_file_path, show_parsed_events_only, event, overlay_event
        )
        app.run()


if __name__ == "__main__":
    main()
