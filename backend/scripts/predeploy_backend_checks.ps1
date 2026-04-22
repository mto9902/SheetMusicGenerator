$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\\..")
Set-Location $repoRoot

Write-Host "Running backend compile check..."
python -m compileall backend/app

Write-Host "Running backend regression tests..."
python -m unittest backend.tests.test_generator_regressions
