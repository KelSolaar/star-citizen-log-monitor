# Star Citizen Log Monitor

An opinionated log monitor for [Star Citizen](https://robertsspaceindustries.com/)
with an emphasis put on extracting combat related data.

![Star Citizen Log Monitor](Star_Citizen_Log_Monitor.png)

## Usage

Review the script! Never execute directly a script from an untrusted source
without having verified its content prior!

### Quick Start (Windows)

For Windows users, a batch file `star-citizen-log-monitor.bat` is provided for easy execution. Simply edit the `SC_DIR` variable to point to your Star Citizen installation directory and run the batch file.

### Command Line

Assuming that [Astral'uv](https://docs.astral.sh/uv/getting-started/installation/) is installed:

```shell
uv run https://raw.githubusercontent.com/KelSolaar/star-citizen-log-monitor/refs/heads/master/star_citizen_log_monitor.py
```

Use `CTRL + Q` to quit.

### Command Options

| Option                                | Description                                                              | Default                                                               |
|:--------------------------------------|:-------------------------------------------------------------------------|:----------------------------------------------------------------------|
| `--log-file-path PATH`                | Path to the Star Citizen Game.log file                                   | `C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Game.log` |
| `--enable-organization-fetching BOOL` | Enable/disable player organization fetching                              | `True`                                                                |
| `--show-parsed-events-only BOOL`      | Show only parsed events (hide raw log lines)                             | `True`                                                                |
| `--event TYPE`                        | Filter to specific event types<br>*(can be used multiple times)*         | All events                                                            |
| `--overlay`                           | Enable overlay mode with transparent window                              | Disabled                                                              |
| `--overlay-event TYPE`                | Filter overlay to specific event types<br>*(can be used multiple times)* | Uses `--event` filter                                                 |
| `--overlay-lines NUMBER`              | Number of lines to show in overlay                                       | `3`                                                                   |
| `--overlay-display NUMBER`            | Display number for overlay<br>*(for multi-monitor setups)*               | `0`                                                                   |
| `--overlay-font-size NUMBER`          | Font size for overlay text                                               | `12`                                                                  |

### Examples

Read a specific log file:
```shell
uv run star_citizen_log_monitor.py --log-file-path "C:\Path\To\Game.log"
```

Enable overlay mode with filtered events:
```shell
uv run star_citizen_log_monitor.py --overlay --overlay-event actor-death --overlay-event vehicle-destruction
```

Filter to specific events in the main display:
```shell
uv run star_citizen_log_monitor.py --event actor-death --event actor-state-corpse --event vehicle-destruction
```

## About

**Star Citizen Log Monitor** by Thomas Mansencal

Copyright 2025 Thomas Mansencal

This software is released under terms of BSD-3-Clause: https://opensource.org/licenses/BSD-3-Clause
