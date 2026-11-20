@echo off
cd /d "%~dp0"
echo Confirme somente depois de conferir que todas as etiquetas sairam corretamente.
set /p "lote=Cole o caminho da pasta do lote (_processamento\data-hora): "
".venv\Scripts\python.exe" etiquetas.py --confirm-printed "%lote%"
pause
