@echo off
powershell.exe -NoProfile -Command "Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile -NoExit -File \"%~dp0Limpar-Spooler.ps1\"'"
