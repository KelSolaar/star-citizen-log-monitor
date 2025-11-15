REM Paste your path to the Star Citizen LIVE game directory (replace with the PTU as required).
set SC_DIR="C:\Program Files\Roberts Space Industries\StarCitizen\LIVE"
set UV_PATH="%HOMEDRIVE%%HOMEPATH%\.local\bin\uv"

REM Ensure that `uv` is installed.
if not exist "%UV_PATH%" (
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
)

REM Run it!
%UV_PATH% run ./star_citizen_log_monitor.py --log-file-path=%SC_DIR%\Game.log --overlay --overlay-event actor-death --overlay-event vehicle-destruction --overlay-event vehicle-destruction --overlay-event actor-state-corpse --overlay-event actor-stall

REM Alternative launch from Github:
REM %UV_PATH% run https://raw.githubusercontent.com/KelSolaar/star-citizen-log-monitor/refs/heads/master/star_citizen_log_monitor.py --log-file-path=%SC_DIR%\Game.log --overlay --overlay-event actor-death --overlay-event vehicle-destruction --overlay-event vehicle-destruction --overlay-event actor-state-corpse --overlay-event actor-stall

pause