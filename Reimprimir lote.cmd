@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo REIMPRESSAO: envia novamente todas as paginas do lote escolhido.
echo Confira antes se a fila esta vazia e se deseja outra copia.
set /p "lote=Cole o nome ou caminho da pasta do lote: "
if not defined lote exit /b 1
".venv\Scripts\python.exe" etiquetas.py --reprint "%lote%"
pause
