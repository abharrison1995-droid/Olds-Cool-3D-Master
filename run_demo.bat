@echo off
REM 3D MASTER:2005 — Run the knight recipe demo (headless asset generation)
cd /d "%~dp0"
echo Generating knight demo assets...
python -m am3d.recipes --recipe scripts/knight_recipe.json --out ./assets/demo
echo.
echo === Done ===
pause