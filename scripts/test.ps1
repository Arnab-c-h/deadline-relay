$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    uv run ruff check relay tests scripts
    if ($LASTEXITCODE -ne 0) { throw 'Python lint failed' }
    uv run pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Python tests failed' }
    Push-Location frontend
    try {
        npm.cmd test -- --run
        if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed' }
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    } finally { Pop-Location }
} finally { Pop-Location }
