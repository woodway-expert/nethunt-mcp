Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $RepoRoot ".env"

if (Test-Path -LiteralPath $EnvFile) {
    foreach ($Line in Get-Content -LiteralPath $EnvFile) {
        if ([string]::IsNullOrWhiteSpace($Line)) {
            continue
        }
        if ($Line.TrimStart().StartsWith("#")) {
            continue
        }
        if ($Line -notmatch '^\s*([^=\s]+)\s*=\s*(.*)\s*$') {
            continue
        }

        $Name = $Matches[1]
        $Value = $Matches[2]
        if (
            ($Value.StartsWith('"') -and $Value.EndsWith('"')) -or
            ($Value.StartsWith("'") -and $Value.EndsWith("'"))
        ) {
            $Value = $Value.Substring(1, $Value.Length - 2)
        }
        Set-Item -LiteralPath "Env:$Name" -Value $Value
    }
}

$SourcePath = Join-Path $RepoRoot "src"
if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = $SourcePath
}
else {
    $env:PYTHONPATH = "$SourcePath;$($env:PYTHONPATH)"
}

$Python = Join-Path $RepoRoot ".venv\\Scripts\\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
}

& $Python -m nethunt_mcp
exit $LASTEXITCODE
