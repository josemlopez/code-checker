param([ValidateRange(1024,65535)][int]$Port = 8873, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$pythonExe = Join-Path $projectDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    & python -m venv (Join-Path $projectDir '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno Python.' }
    & $pythonExe -m pip install -r (Join-Path $projectDir 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }
}
$url = "http://127.0.0.1:$Port"
$existing = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($existing) {
    try {
        $config = Invoke-RestMethod "$url/api/config" -TimeoutSec 3
        if ($config.policy_version -notlike 'agent-evolution-*') { throw 'Servicio diferente' }
        if (-not $NoBrowser) { Start-Process $url }
        Write-Output "Code Checker ya está disponible en $url"
        return
    } catch { throw "El puerto $Port está ocupado por otro servicio. Usa -Port con un puerto libre." }
}
Write-Output "Code Checker: $url · Ctrl+C para detener."
Push-Location -LiteralPath $projectDir
try {
    if (-not $NoBrowser) { Start-Process $url }
    & $pythonExe -m uvicorn code_checker.app:app --host 127.0.0.1 --port $Port
} finally { Pop-Location }
