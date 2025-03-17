Rem Paste your path to the star citizen LIVE game directory (replace this with the PTU if needed)
set SC_DIR=H:\Roberts Space Industries\StarCitizen\LIVE
set UV_PATH=%HOMEDRIVE%%HOMEPATH%\.local\bin\uv

Rem Ensure uv is installed
if not exist "%UV_PATH%" (
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
)

Rem run it!
%UV_PATH% run ./star_citizen_log_monitor.py --log-file-path="%SC_DIR%\Game.log"