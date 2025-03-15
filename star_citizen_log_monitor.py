# /// script
# dependencies = [
#   "aiofiles>=24,<25",
#   "click>=8,<9",
#   "textual>=2,<3",
# ]
# ///

"""
Star Citizen Log Monitor
========================

An opinionated log monitor for `Star Citizen <https://robertsspaceindustries.com/>`__
with an emphasis put on extracting combat related data.
"""

import asyncio
import re
import traceback
from functools import wraps
from typing import Callable

import aiofiles
import click
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

__version__ = "0.1.5"

__all__ = [
    "PATTERN_TIMESTAMP",
    "PATTERN_NOTICE",
    "THEME_DEFAULT",
    "catch_exception",
    "Logger",
    "EventHighlighter",
    "beautify_entity_name",
    "parse_event_on_client_spawned",
    "parse_event_connect_started",
    "parse_event_on_client_connected",
    "parse_event_request_quit_lobby",
    "parse_event_actor_death",
    "parse_vehicle_destruction",
    "parse_requesting_transition_event",
    "EVENT_PARSERS",
    "StarCitizenLogMonitorApp",
]

PATTERN_TIMESTAMP = r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z)"

PATTERN_NOTICE = "<" + PATTERN_TIMESTAMP + ">" + r" \[Notice]\ "

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
        "sclh.causedby": "italic #DC143C",
        "sclh.cause": "italic #A52A2A",
    }
)


def catch_exception(function: Callable) -> Callable:
    @wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            tb = traceback.format_exc()

            return f"Exception in {function.__name__}: {tb}"

    return wrapper


class Logger(Log):
    def flush(self) -> None:
        pass


class EventHighlighter(RegexHighlighter):
    base_style = "sclh."
    highlights = [
        PATTERN_TIMESTAMP,
        r"(?P<classifier>Zone): (?P<zone>[\w_-]+),",
        r"(?P<classifier>Requester): (?P<requester>[\w_-]+)",
        # Actor Death
        r"(?P<actordeath>\[Actor Death\])",
        r"(?P<classifier>Victim): (?P<victim>[\w_-]+),",
        r"(?P<classifier>Killer): (?P<killer>[\w_-]+),",
        r"(?P<classifier>Weapon): (?P<weapon>[\w_-]+)",
        # Vehicle Destruction
        r"(?P<vehicledestruction>\[Vehicle Destruction\])",
        r"(?P<classifier>Vehicle): (?P<vehicle>[\w_-]+),",
        r"(?P<classifier>Driver): (?P<driver>[\w_-]+),",
        r"(?P<classifier>Caused By): (?P<causedby>[\w_-]+),",
        r"(?P<classifier>Cause): (?P<cause>[\w_-]+),",
    ]


def beautify_entity_name(name: str) -> str:
    return next(iter(name.rsplit("_", 1)), name)


@catch_exception
def parse_event_on_client_spawned(log_line: str) -> str:
    pattern = re.compile(
        "<"
        + PATTERN_TIMESTAMP
        + "> "
        + r"\[CSessionManager::OnClientSpawned\] Spawned!"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return f"{data['timestamp']} [Client Spawned]"

    return None


@catch_exception
def parse_event_connect_started(log_line: str) -> str:
    pattern = re.compile(
        "<"
        + PATTERN_TIMESTAMP
        + "> "
        + r"\[CSessionManager::ConnectCmd\] Connect started!"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return f"{data['timestamp']} [Connect Started]"

    return None


@catch_exception
def parse_event_on_client_connected(log_line: str) -> str:
    pattern = re.compile(
        "<"
        + PATTERN_TIMESTAMP
        + "> "
        + r"\[CSessionManager::OnClientConnected\] Connected!"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return f"{data['timestamp']} [Client Connected]"

    return None


@catch_exception
def parse_event_request_quit_lobby(log_line: str) -> str:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<\[EALobby\] EALobbyQuit> \[EALobby\]\[CEALobby::RequestQuitLobby\] (?P<requester>[\w_-]+) Requesting QuitLobby"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return (
            f"{data['timestamp']} [Request Quit Lobby] Requester: {data['requester']}"
        )

    return None


@catch_exception
def parse_event_actor_death(log_line: str) -> str:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<Actor Death> CActor::Kill: '(?P<victim>[\w_-]+)' \[\d+\] in zone '(?P<zone>[\w_-]+)' killed by '(?P<killer>[\w_-]+)' \[\d+\] using '(?P<weapon>[\w_-]+)' \[Class (?P<weapon_class>[\w_-]+)\] with damage type '(?P<damage_type>[\w_-]+)' from direction x: (?P<direction_x>[-\d.]+), y: (?P<direction_y>[-\d.]+), z: (?P<direction_z>[-\d.]+)"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return (
            f"{data['timestamp']} [Actor Death] "
            f"Victim: {beautify_entity_name(data['victim'])}, "
            f"Killer: {beautify_entity_name(data['killer'])}, "
            f"Zone: {beautify_entity_name(data['zone'])}, "
            f"Weapon: {beautify_entity_name(data['weapon'])}"
        )

    return None


@catch_exception
def parse_vehicle_destruction(log_line: str) -> str:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<Vehicle Destruction> CVehicle::OnAdvanceDestroyLevel: Vehicle '(?P<vehicle_name>[\w_-]+)' \[(?P<vehicle_id>\d+)\] in zone '(?P<zone>[\w_-]+)' \[pos x: (?P<pos_x>[-\d.]+), y: (?P<pos_y>[-\d.]+), z: (?P<pos_z>[-\d.]+) vel x: (?P<vel_x>[-\d.]+), y: (?P<vel_y>[-\d.]+), z: (?P<vel_z>[-\d.]+)\] driven by '(?P<driver>[\w_-]+)' \[(?P<driver_id>\d+)\] advanced from destroy level (?P<destroy_level_from>\d+) to (?P<destroy_level_to>\d+) caused by '(?P<causer>[\w_-]+)' \[(?P<causer_id>\d+)\] with '(?P<cause>[^\']+)'"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return (
            f"{data['timestamp']} [Vehicle Destruction] "
            f"Vehicle: {beautify_entity_name(data['vehicle_name'])}, "
            f"Driver: {beautify_entity_name(data['driver'])}, "
            f"Caused By: {beautify_entity_name(data['causer'])}, "
            f"Cause: {data['cause']}, "
            f"Zone: {beautify_entity_name(data['zone'])}"
        )

    return None


@catch_exception
def parse_requesting_transition_event(log_line: str) -> str:
    pattern = re.compile(
        PATTERN_NOTICE
        + r"<Requesting Transition> (?P<component>[^\|]+) \| (?P<status>[^\|]+) \| (?P<current_system>[^\|]+) \| (?P<host>[\w_-]+) \[(?P<host_id>\d+)\] \| Transitioning from zone (?P<from_zone>[\w_-]+) in (?P<from_system>[\w_-]+) to zone (?P<to_zone>[\w_-]+) in (?P<to_system>[\w_-]+) \[(?P<team>[\w_-]+)\]\[(?P<category>\w+)\]"
    )

    if search := pattern.search(log_line):
        data = search.groupdict()

        return (
            f"{data['timestamp']} [Requesting Transition] "
            f"From: {data['from_system']} ({data['from_zone']}), "
            f"To: {data['to_system']} ({data['to_zone']})"
        )

    return None


EVENT_PARSERS = [
    parse_event_on_client_spawned,
    parse_event_connect_started,
    parse_event_on_client_connected,
    parse_event_request_quit_lobby,
    parse_event_actor_death,
    parse_vehicle_destruction,
    parse_requesting_transition_event,
]


class StarCitizenLogMonitorApp(App):
    def __init__(self, log_file_path: str):
        super().__init__()

        self.log_file_path = log_file_path

        self.console = Console(theme=THEME_DEFAULT)

        self.logger = Logger(highlight=True)
        self.logger.highlighter = EventHighlighter()

        self.worker: Worker | None = None

    def compose(self) -> ComposeResult:
        yield self.logger

    def on_mount(self):
        self.logger.write_line(f"[ {self.__class__.__name__} - {__version__} ]")
        self.worker = self.run_worker(self.monitor())

    def process_line(self, line: str):
        for event_parser in EVENT_PARSERS:
            if parsed_event := event_parser(line):
                self.logger.write_line(parsed_event)

    async def monitor(self):
        try:
            async with aiofiles.open(self.log_file_path, mode="r") as file:
                lines = await file.readlines()

                for line in lines:
                    self.process_line(line)

                while True:
                    line = await file.readline()

                    if not line:
                        await asyncio.sleep(0.05)

                        continue

                    self.process_line(line)

        except Exception as error:
            self.process_line(str(error))


@click.command()
@click.option(
    "--log-file-path",
    default=r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Game.log",
    help="Log file path",
)
def main(log_file_path: str) -> None:
    app = StarCitizenLogMonitorApp(log_file_path)
    app.run()


if __name__ == "__main__":
    main()
