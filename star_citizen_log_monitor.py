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
import traceback
from datetime import datetime
from functools import wraps
from pathlib import Path
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

__version__ = "0.7.0"

__all__ = [
    "LOCAL_TIMEZONE",
    "PATTERN_TIMESTAMP_RAW",
    "PATTERN_TIMESTAMP_BEAUTIFIED",
    "PATTERN_NOTICE",
    "THEME_DEFAULT",
    "PATH_EXCEPTION_LOG",
    "catch_exception",
    "fetch_page",
    "CACHE_ORGANIZATIONS",
    "TTL_ORGANIZATION",
    "extract_organization_name",
    "Logger",
    "EventHighlighter",
    "beautify_timestamp",
    "beautify_entity_name",
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
    "StarCitizenLogMonitorApp",
]

LOCAL_TIMEZONE = tzlocal.get_localzone()

PATTERN_TIMESTAMP_RAW = r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z)"
PATTERN_TIMESTAMP_BEAUTIFIED = (
    r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:AM|PM))"
)

PATTERN_NOTICE = "<" + PATTERN_TIMESTAMP_RAW + ">" + r" \[Notice]\ "

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
    highlights = [
        PATTERN_TIMESTAMP_BEAUTIFIED,
        r"(?P<classifier>Zone): (?P<zone>[\w_-]+),",
        r"(?P<classifier>Requester): (?P<requester>[\w_-]+)",
        r"(?P<classifier>Requester): (?P<requester>[\w_-]+ \([\w_-]+\))",
        # Actor Death
        r"(?P<actordeath>\[Actor Death\])",
        r"(?P<classifier>Victim): (?P<victim>[\w_-]+),",
        r"(?P<classifier>Victim): (?P<victim>[\w_-]+ \([\w_-]+\)),",
        r"(?P<classifier>Killer): (?P<killer>[\w_-]+),",
        r"(?P<classifier>Killer): (?P<killer>[\w_-]+ \([\w_-]+\)),",
        r"(?P<classifier>Weapon): (?P<weapon>[\w_-]+)",
        # Vehicle Destruction
        r"(?P<vehicledestruction>\[Vehicle Destruction\])",
        r"(?P<classifier>Vehicle): (?P<vehicle>[\w_-]+),",
        r"(?P<classifier>Driver): (?P<driver>[\w_-]+),",
        r"(?P<classifier>Driver): (?P<driver>[\w_-]+ \([\w_-]+\)),",
        r"(?P<classifier>Caused By): (?P<causer>[\w_-]+),",
        r"(?P<classifier>Caused By): (?P<causer>[\w_-]+ \([\w_-]+\)),",
        r"(?P<classifier>Cause): (?P<cause>[\w_-]+),",
        # Actor State Corpse
        r"(?P<corpse>\[Corpse\])",
        r"(?P<classifier>Player): (?P<player>[\w_-]+)",
        r"(?P<classifier>Player): (?P<player>[\w_-]+ \([\w_-]+\))",
        # Actor Stall
        r"(?P<actorstall>\[Actor Stall\])",
    ]


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
        + r"<\[ActorState\] Corpse> \[ACTOR STATE\]\[SSCActorStateCVars::LogCorpse\] Player '(?P<player>[\w_-]+)' <remote client>: IsCorpseEnabled: Yes, there is no local inventory\. \[Team_ActorFeatures\]\[Actor\]"
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


EVENT_PARSERS = [
    parse_event_on_client_spawned,
    parse_event_connect_started,
    parse_event_on_client_connected,
    parse_event_request_quit_lobby,
    parse_event_actor_death,
    parse_event_vehicle_destruction,
    parse_event_requesting_transition,
    parse_event_actor_state_corpse,
    parse_event_actor_stall,
    parse_event_lost_spawn_reservation,
]


class StarCitizenLogMonitorApp(App):
    def __init__(self, log_file_path: str, show_parsed_events_only: bool = True):
        super().__init__()

        self.log_file_path = log_file_path
        self.show_parsed_events_only = show_parsed_events_only

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

        for event_parser in EVENT_PARSERS:
            if parsed_event := await event_parser(line):
                self.logger.write_line(parsed_event)

    async def monitor(self):
        # External loop reloading the log file when the game restarts.
        while True:
            self.log_file_size = os.path.getsize(self.log_file_path)

            try:
                async with aiofiles.open(self.log_file_path, mode="r", encoding="ISO-8859-2") as file:
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
                    exception_log.write(f'{datetime.now().strftime("%H:%M:%S")}: {error}\n')

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
def main(
    log_file_path: str,
    enable_organization_fetching: bool,
    show_parsed_events_only: bool,
) -> None:
    global _ENABLE_ORGANIZATION_FETCHING

    _ENABLE_ORGANIZATION_FETCHING = enable_organization_fetching

    app = StarCitizenLogMonitorApp(log_file_path, show_parsed_events_only)
    app.run()


if __name__ == "__main__":
    main()
