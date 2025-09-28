# /// script
# dependencies = [
#   "aiofiles>=24,<25",
#   "aiohttp>=3,<4",
#   "beautifulsoup4>=4,<5",
#   "click>=8,<9",
#   "pickledb>=1,<2",
#   "pytz>=2025",
#   "textual>=2,<3",
#   "tzlocal>=5,<6",
# ]
# ///

"""
Star Citizen Log Monitor
========================

An opinionated log monitor for `Star Citizen <https://robertsspaceindustries.com/>`__
with an emphasis put on extracting combat related data.
"""

import asyncio
import os
import re
import time
import tkinter as tk
import tkinter.font as tkFont
import traceback
from collections import deque
from datetime import datetime
from functools import wraps
from pathlib import Path
from threading import Thread
from typing import Callable

import aiofiles
import aiohttp
import click
import pytz
import tzlocal
from bs4 import BeautifulSoup
from pickledb import PickleDB
from rich.console import Console
from rich.highlighter import RegexHighlighter
from rich.theme import Theme
from textual.app import App, ComposeResult
from textual.widgets import Log
from textual.worker import Worker

__author__ = "Thomas Mansencal"
__copyright__ = "Copyright 2025 Thomas Mansencal"
__license__ = "BSD-3-Clause - https://opensource.org/licenses/BSD-3-Clause"
__maintainer__ = "Thomas Mansencal"
__status__ = "Production"

__version__ = "0.9.1"

__all__ = [
    "LOCAL_TIMEZONE",
    "PATTERN_TIMESTAMP_RAW",
    "PATTERN_TIMESTAMP_BEAUTIFIED",
    "PATTERN_NOTICE",
    "HIGHLIGHT_PATTERNS",
    "COLOUR_MAPPING",
    "THEME_DEFAULT",
    "PATH_EXCEPTION_LOG",
    "CACHE_ORGANIZATIONS",
    "TTL_ORGANIZATION",
    "catch_exception",
    "fetch_page",
    "extract_organization_name",
    "beautify_timestamp",
    "beautify_entity_name",
    "Logger",
    "EventHighlighter",
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
    (r"(?P<classifier>Zone): (?P<zone>[\w_-]+),", "classifier", "zone"),
    (r"(?P<classifier>Requester): (?P<requester>[\w_-]+)", "classifier", "requester"),
    (
        r"(?P<classifier>Requester): (?P<requester>[\w_-]+ \([\w_-]+\))",
        "classifier",
        "requester",
    ),
    # Actor Death
    (r"(?P<actordeath>\[Actor Death\])", "actordeath"),
    (r"(?P<classifier>Victim): (?P<victim>[\w_-]+),", "classifier", "victim"),
    (
        r"(?P<classifier>Victim): (?P<victim>[\w_-]+ \([\w_-]+\)),",
        "classifier",
        "victim",
    ),
    (r"(?P<classifier>Killer): (?P<killer>[\w_-]+),", "classifier", "killer"),
    (
        r"(?P<classifier>Killer): (?P<killer>[\w_-]+ \([\w_-]+\)),",
        "classifier",
        "killer",
    ),
    (r"(?P<classifier>Weapon): (?P<weapon>[\w_-]+)", "classifier", "weapon"),
    # Vehicle Destruction
    (r"(?P<vehicledestruction>\[Vehicle Destruction\])", "vehicledestruction"),
    (r"(?P<classifier>Vehicle): (?P<vehicle>[\w_-]+),", "classifier", "vehicle"),
    (r"(?P<classifier>Driver): (?P<driver>[\w_-]+),", "classifier", "driver"),
    (
        r"(?P<classifier>Driver): (?P<driver>[\w_-]+ \([\w_-]+\)),",
        "classifier",
        "driver",
    ),
    (r"(?P<classifier>Caused By): (?P<causer>[\w_-]+),", "classifier", "causer"),
    (
        r"(?P<classifier>Caused By): (?P<causer>[\w_-]+ \([\w_-]+\)),",
        "classifier",
        "causer",
    ),
    (r"(?P<classifier>Cause): (?P<cause>[\w_-]+),", "classifier", "cause"),
    # Actor State Corpse
    (r"(?P<corpse>\[Corpse\])", "corpse"),
    (r"(?P<classifier>Player): (?P<player>[\w_-]+(?:\s+\([\w_-]+\))?)", "classifier", "player"),
    # Actor Stall
    (r"(?P<actorstall>\[Actor Stall\])", "actorstall"),
]

COLOUR_MAPPING = {
    "timestamp": "#1E90FF",  # DodgerBlue
    "classifier": "white",  # Bold white
    "zone": "#32CD32",  # LimeGreen
    "requester": "#DC143C",  # Crimson
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
    "default": "white",  # Default white
}

THEME_DEFAULT = Theme(
    {
        "sclh.timestamp": "italic #1E90FF",
        "sclh.classifier": "bold",
        "sclh.zone": "italic #32CD32",
        "sclh.requester": "italic #DC143C",
        # Actor Death
        "sclh.actordeath": "bold #DC143C",
        "sclh.victim": "italic #FF69B4",
        "sclh.killer": "italic #DC143C",
        "sclh.weapon": "italic #A52A2A",
        # Vehicle Destruction
        "sclh.vehicledestruction": "bold orange1",
        "sclh.vehicle": "italic #FF69B4",
        "sclh.driver": "italic #FF69B4",
        "sclh.causer": "italic #DC143C",
        "sclh.cause": "italic #A52A2A",
        # Actor State Corpse
        "sclh.corpse": "bold #DC143C",
        "sclh.player": "italic #FF69B4",
        # Actor Stall
        "sclh.actorstall": "bold orange1",
    }
)

PATH_EXCEPTION_LOG = Path(__file__).parent / ".exceptions"


def catch_exception(function: Callable) -> Callable:
    @wraps(function)
    async def wrapper(*args, **kwargs):
        try:
            return await function(*args, **kwargs)
        except Exception:
            tb = traceback.format_exc()

            return f"Exception in {function.__name__}: {tb}"

    return wrapper


async def fetch_page(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url) as response:
        return await response.text()


CACHE_ORGANIZATIONS = PickleDB(Path(__file__).parent / ".organizations")

TTL_ORGANIZATION = 3600 * 24 * 72  # 3 Days

_ENABLE_ORGANIZATION_FETCHING = True


async def extract_organization_name(player: str) -> str | None:
    if not _ENABLE_ORGANIZATION_FETCHING:
        return None

    if player in CACHE_ORGANIZATIONS.all():
        data = CACHE_ORGANIZATIONS.get(player)

        if time.time() < data["expiration"]:
            return data["organization"]

    url = f"https://robertsspaceindustries.com/en/citizens/{player}"
    async with aiohttp.ClientSession() as session:
        html_content = await fetch_page(session, url)
        soup = BeautifulSoup(html_content, "html.parser")
        sid = soup.find(text="Spectrum Identification (SID)")
        if sid is None:
            CACHE_ORGANIZATIONS.set(
                player,
                {"organization": None, "expiration": time.time() + TTL_ORGANIZATION},
            )

            CACHE_ORGANIZATIONS.save()

            return None

        organization = sid.find_next().text.strip()

        CACHE_ORGANIZATIONS.set(
            player,
            {
                "organization": organization,
                "expiration": time.time() + TTL_ORGANIZATION,
            },
        )

        CACHE_ORGANIZATIONS.save()

        return organization


class Logger(Log):
    def flush(self) -> None:
        pass


class EventHighlighter(RegexHighlighter):
    base_style = "sclh."
    highlights = [pattern[0] for pattern in HIGHLIGHT_PATTERNS]


def beautify_timestamp(timestamp: str) -> str:
    utc_timestamp = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    utc_timestamp = utc_timestamp.replace(tzinfo=pytz.UTC)

    local_timestamp = utc_timestamp.astimezone(LOCAL_TIMEZONE)

    return local_timestamp.strftime("%Y-%m-%d %I:%M:%S%p")


def beautify_entity_name(name: str) -> str:
    if match := re.match(r"([\w_-]+)_\d{10,}$", name):
        return match.group(1)

    return name


@catch_exception
async def parse_event_on_client_spawned(log_line: str) -> str:
    pattern = re.compile(
        "<"
        + PATTERN_TIMESTAMP_RAW
        + "> "
        + r"\[CSessionManager::OnClientSpawned\] Spawned!"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return f"{beautify_timestamp(data['timestamp'])} [Client Spawned]"

    return None


@catch_exception
async def parse_event_connect_started(log_line: str) -> str:
    pattern = re.compile(
        "<"
        + PATTERN_TIMESTAMP_RAW
        + "> "
        + r"\[CSessionManager::ConnectCmd\] Connect started!"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return f"{beautify_timestamp(data['timestamp'])} [Connect Started]"

    return None


@catch_exception
async def parse_event_on_client_connected(log_line: str) -> str:
    pattern = re.compile(
        "<"
        + PATTERN_TIMESTAMP_RAW
        + "> "
        + r"\[CSessionManager::OnClientConnected\] Connected!"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return f"{beautify_timestamp(data['timestamp'])} [Client Connected]"

    return None


@catch_exception
async def parse_event_request_quit_lobby(log_line: str) -> str:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<\[EALobby\] EALobbyQuit> \[EALobby\]\[CEALobby::RequestQuitLobby\] (?P<requester>[\w_-]+) Requesting QuitLobby"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        requester = beautify_entity_name(data["requester"])
        if organization := await extract_organization_name(requester):
            requester = f"{requester} ({organization})"

        return f"{beautify_timestamp(data['timestamp'])} [Request Quit Lobby] Requester: {requester}"

    return None


@catch_exception
async def parse_event_actor_death(log_line: str) -> str:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<Actor Death> CActor::Kill: '(?P<victim>[\w_-]+)' \[\d+\] in zone '(?P<zone>[\w_-]+)' killed by '(?P<killer>[\w_-]+)' \[\d+\] using '(?P<weapon>[\w_-]+)' \[Class (?P<weapon_class>[\w_-]+)\] with damage type '(?P<damage_type>[\w_-]+)' from direction x: (?P<direction_x>[-\d.]+), y: (?P<direction_y>[-\d.]+), z: (?P<direction_z>[-\d.]+)"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        victim = beautify_entity_name(data["victim"])
        if organization := await extract_organization_name(victim):
            victim = f"{victim} ({organization})"

        killer = beautify_entity_name(data["killer"])
        if organization := await extract_organization_name(killer):
            killer = f"{killer} ({organization})"

        return (
            f"{beautify_timestamp(data['timestamp'])} [Actor Death] "
            f"Victim: {victim}, "
            f"Killer: {killer}, "
            f"Zone: {beautify_entity_name(data['zone'])}, "
            f"Weapon: {beautify_entity_name(data['weapon'])}"
        )

    return None


@catch_exception
async def parse_event_vehicle_destruction(log_line: str) -> str:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<Vehicle Destruction> CVehicle::OnAdvanceDestroyLevel: Vehicle '(?P<vehicle_name>[\w_-]+)' \[(?P<vehicle_id>\d+)\] in zone '(?P<zone>[\w_-]+)' \[pos x: (?P<pos_x>[-\d.]+), y: (?P<pos_y>[-\d.]+), z: (?P<pos_z>[-\d.]+) vel x: (?P<vel_x>[-\d.]+), y: (?P<vel_y>[-\d.]+), z: (?P<vel_z>[-\d.]+)\] driven by '(?P<driver>[\w_-]+)' \[(?P<driver_id>\d+)\] advanced from destroy level (?P<destroy_level_from>\d+) to (?P<destroy_level_to>\d+) caused by '(?P<causer>[\w_-]+)' \[(?P<causer_id>\d+)\] with '(?P<cause>[^\']+)'"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        driver = beautify_entity_name(data["driver"])
        if organization := await extract_organization_name(driver):
            driver = f"{driver} ({organization})"

        causer = beautify_entity_name(data["causer"])
        if organization := await extract_organization_name(causer):
            causer = f"{causer} ({organization})"

        return (
            f"{beautify_timestamp(data['timestamp'])} [Vehicle Destruction] "
            f"Vehicle: {beautify_entity_name(data['vehicle_name'])}, "
            f"Driver: {driver}, "
            f"Caused By: {causer}, "
            f"Cause: {data['cause']}, "
            f"Zone: {beautify_entity_name(data['zone'])}"
        )

    return None


@catch_exception
async def parse_event_requesting_transition(log_line: str) -> str:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<Requesting Transition> (?P<component>[^\|]+) \| (?P<status>[^\|]+) \| (?P<current_system>[^\|]+) \| (?P<host>[\w_-]+) \[(?P<host_id>\d+)\] \| Transitioning from zone (?P<from_zone>[\w_-]+) in (?P<from_system>[\w_-]+) to zone (?P<to_zone>[\w_-]+) in (?P<to_system>[\w_-]+) \[(?P<team>[\w_-]+)\]\[(?P<category>\w+)\]"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return (
            f"{beautify_timestamp(data['timestamp'])} [Requesting Transition] "
            f"From: {data['from_system']} ({data['from_zone']}), "
            f"To: {data['to_system']} ({data['to_zone']})"
        )

    return None


@catch_exception
async def parse_event_actor_state_corpse(log_line: str) -> str:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<\[ActorState\] Corpse> \[ACTOR STATE\]\[SSCActorStateCVars::LogCorpse\] Player '(?P<player>[\w_-]+)' <remote client>: Running corpsify for corpse\. \[Team_ActorFeatures\]\[Actor\]"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        player = beautify_entity_name(data["player"])
        if organization := await extract_organization_name(player):
            player = f"{player} ({organization})"

        return f"{beautify_timestamp(data['timestamp'])} [Corpse] Player: {player}"

    return None


@catch_exception
async def parse_event_actor_stall(log_line: str) -> str:
    pattern = re.compile(
        r"<(?P<timestamp>[\d\-T:.Z]+)> \[Notice\] <Actor stall> Actor stall detected, Player: (?P<player>[\w_-]+), Type: (?P<type>\w+), Length: (?P<length>[\d.]+)\. \[Team_ActorTech\]\[Actor\]"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        player = beautify_entity_name(data["player"])
        if organization := await extract_organization_name(player):
            player = f"{player} ({organization})"

        return f"{beautify_timestamp(data['timestamp'])} [Actor Stall] Player: {player}, Length: {round(float(data['length']), 1)}"

    return None


@catch_exception
async def parse_event_lost_spawn_reservation(log_line: str) -> str:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<Spawn Flow> CSCPlayerPUSpawningComponent::UnregisterFromExternalSystems: "
        + r"Player '(?P<player>[\w_-]+)' \[(?P<player_id>\d+)\] lost reservation for spawnpoint (?P<spawnpoint>\w+) "
        + r"\[(?P<spawnpoint_id>\d+)\] at location (?P<location>\d+) "
        + r"\[Team_ActorFeatures\]\[Gamerules\]"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        player = beautify_entity_name(data["player"])
        if organization := await extract_organization_name(player):
            player = f"{player} ({organization})"

        return f"{beautify_timestamp(data['timestamp'])} [Spawn Lost] Player: {player}"

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


class OverlayWindow:
    """
    A transparent overlay window that displays log lines as floating text.
    Uses tkinter with color key transparency to show text without background.
    """

    def __init__(self, max_lines: int = 3, display: int = 0, font_size: int = 14):
        """
        Initialize overlay window.

        Args:
            max_lines: Maximum number of lines to display
            display: Display number for multi-monitor setups
            font_size: Font size for displayed text
        """
        self.max_lines = max_lines
        self.display = display
        self.font_size = font_size
        self.lines = deque(maxlen=max_lines)
        self.root = None
        self.canvas = None
        self.text_items = []
        self.running = False

    def start(self):
        self.running = True
        self.root = tk.Tk()
        self.root.title("Star Citizen Log Overlay")

        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.wm_attributes("-topmost", 1)

        transparent_color = "#FF00FF"
        self.root.configure(bg=transparent_color)
        self.root.attributes("-transparentcolor", transparent_color)

        self.root.update_idletasks()

        screen_width = self.root.winfo_screenwidth()

        x_offset = screen_width * self.display if self.display > 0 else 0

        window_width = int(screen_width * 0.66)
        window_height = self.max_lines * (self.font_size + 5) + 20

        x = int((screen_width - window_width) / 2) + x_offset
        y = 10

        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")

        self.root.update_idletasks()

        self.canvas = tk.Canvas(
            self.root,
            bg=transparent_color,
            highlightthickness=0,
            borderwidth=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.root.bind("<Escape>", lambda _: self.stop())
        self.root.bind("<Button-1>", self._start_move)
        self.root.bind("<B1-Motion>", self._on_move)
        self.root.protocol("WM_DELETE_WINDOW", self.stop)

        self._keep_on_top()

    def _start_move(self, event):
        self.x = event.x
        self.y = event.y

    def _on_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")

    def _keep_on_top(self):
        if self.running and self.root:
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(1000, self._keep_on_top)

    def _colorize_text(self, text: str):
        segments = []
        matches = []

        for pattern_data in HIGHLIGHT_PATTERNS:
            pattern = pattern_data[0]
            for match in re.finditer(pattern, text):
                for group_name, group_value in match.groupdict().items():
                    if group_value is not None:
                        color_key = group_name
                        start_pos = match.start(group_name)
                        end_pos = match.end(group_name)
                        matches.append((start_pos, end_pos, group_value, color_key))

        matches.sort(key=lambda x: x[0])

        current_pos = 0
        for start, end, matched_text, color_key in matches:
            if start > current_pos:
                segments.append((text[current_pos:start], COLOUR_MAPPING["default"]))

            color = COLOUR_MAPPING.get(color_key, COLOUR_MAPPING["default"])
            segments.append((matched_text, color))
            current_pos = end

        if current_pos < len(text):
            segments.append((text[current_pos:], COLOUR_MAPPING["default"]))

        if not segments:
            segments = [(text, COLOUR_MAPPING["default"])]

        return segments

    def add_line(self, line: str):
        if not self.root:
            return

        self.lines.append(line)
        self._update_display()

    def _update_display(self):
        if not self.canvas:
            return

        for item in self.text_items:
            self.canvas.delete(item)
        self.text_items.clear()

        font_tuple = ("Consolas", self.font_size, "bold")

        if not hasattr(self, "_font"):
            self._font = tkFont.Font(
                family="Consolas", size=self.font_size, weight="bold"
            )

        y_pos = 10
        for line in self.lines:
            segments = self._colorize_text(line)

            x_pos = 10
            for text_segment, color in segments:
                if text_segment:
                    text_item = self.canvas.create_text(
                        x_pos,
                        y_pos,
                        text=text_segment,
                        font=font_tuple,
                        fill=color,
                        anchor="nw",
                    )
                    self.text_items.append(text_item)

                    x_pos += self._font.measure(text_segment)

            y_pos += self.font_size + 5

    def stop(self):
        self.running = False
        if self.root:
            self.root.quit()
            self.root.destroy()

    def mainloop(self):
        if self.root:
            self.root.mainloop()


class StarCitizenLogMonitorApp(App):
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

        self.console = Console(theme=THEME_DEFAULT)

        self.logger = Logger(highlight=True)
        self.logger.highlighter = EventHighlighter()

        self.worker: Worker | None = None

    def compose(self) -> ComposeResult:
        yield self.logger

    def on_mount(self):
        self.logger.write_line(f"[ {self.__class__.__name__} - {__version__} ]")
        self.worker = self.run_worker(self.monitor())

    async def process_line(self, line: str):
        if not self.show_parsed_events_only:
            self.logger.write_line(line)
            if self.overlay_window:
                self.overlay_window.add_line(line.strip())

        for event_key, event_parser in EVENT_PARSERS.items():
            if parsed_event := await event_parser(line):
                # Add to console if event matches console filters
                if event_key in self.event_filters:
                    self.logger.write_line(parsed_event)

                # Add to overlay if event matches overlay filters
                if self.overlay_window and event_key in self.overlay_event_filters:
                    self.overlay_window.add_line(parsed_event)

                # Return after first successful parse to avoid double processing
                if event_key in self.event_filters or (self.overlay_window and event_key in self.overlay_event_filters):
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
                            self.logger.write_line(
                                f"[ {self.__class__.__name__} - {__version__} - Restarting... ]"
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
    default=12,
    help="Font size for overlay text (default: 12)",
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
        overlay_window = OverlayWindow(
            overlay_lines, overlay_display, overlay_font_size
        )
        overlay_window.start()

        overlay_window.add_line("Star Citizen Log Overlay Active")
        overlay_window.add_line("Waiting for log events...")

        app = StarCitizenLogMonitorApp(
            log_file_path, show_parsed_events_only, event, overlay_event, overlay_window
        )
        app_thread = Thread(target=app.run, daemon=True)
        app_thread.start()

        try:
            overlay_window.mainloop()
        finally:
            overlay_window.stop()
    else:
        app = StarCitizenLogMonitorApp(log_file_path, show_parsed_events_only, event, overlay_event)
        app.run()


if __name__ == "__main__":
    main()
