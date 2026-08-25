@echo off
REM 3D MASTER:2005 — Run the full test suite
cd /d "%~dp0"
echo Running 3D MASTER:2005 test suite...
python -m pytest am3d/ -v
echo.
echo === Done ===
pause