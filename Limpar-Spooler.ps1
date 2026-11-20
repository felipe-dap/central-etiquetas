$ErrorActionPreference = 'Stop'
$printerName = & (Join-Path $PSScriptRoot '.venv/Scripts/python.exe') -c 'import sys;sys.path.insert(0,sys.argv[1]);from config import DEFAULT_PRINTER;print(DEFAULT_PRINTER)' $PSScriptRoot
if ($LASTEXITCODE -ne 0 -or -not $printerName) { throw 'Nao foi possivel ler a configuracao da impressora.' }
$logPath = Join-Path $PSScriptRoot 'diagnostico-spooler.txt'
Start-Transcript -Path $logPath -Force
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Execute este script como administrador.'
    }
    $otherJobs = @(Get-Printer | Where-Object Name -ne $printerName | ForEach-Object { Get-PrintJob -PrinterName $_.Name })
    if ($otherJobs.Count -gt 0) { throw 'Existem trabalhos em outras impressoras. Limpeza interrompida para preserva-los.' }
    Get-PrintJob -PrinterName $printerName | Remove-PrintJob
    $spoolDirectory = Join-Path $env:windir 'System32\spool\PRINTERS'
    $resolved = (Resolve-Path -LiteralPath $spoolDirectory).Path
    if ($resolved -ne [IO.Path]::GetFullPath($spoolDirectory)) { throw 'Pasta do spool inesperada.' }
    try {
        Stop-Service Spooler -Force
        Get-ChildItem -LiteralPath $resolved -File | Where-Object Extension -in '.SPL','.SHD' | ForEach-Object {
            Remove-Item -LiteralPath $_.FullName -Force
        }
    } finally {
        Start-Service Spooler
    }
    Get-Service Spooler | Format-Table Name,Status
    Get-Printer -Name $printerName | Format-List Name,PrinterStatus,JobCount,PortName
    Get-PnpDevice -PresentOnly | Where-Object InstanceId -match 'VID_0A5F|USBPRINT' | Format-List Status,FriendlyName,InstanceId
} finally {
    Stop-Transcript
}

