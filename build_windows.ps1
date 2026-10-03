$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
$previousPath = $env:PATH
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
$previousCache = $env:PYINSTALLER_CONFIG_DIR
try {
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Create .venv and install requirements-build.txt before building.'
    }
    $pythonBase = & $python -c 'import sys; print(sys.base_prefix)'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot locate the Python runtime.' }

    # Unrelated tools (e.g. Poppler) may provide an incompatible icuuc.dll on
    # PATH. Qt 6.11 requires the Windows system ICU, not that third-party DLL.
    $env:PATH = @(
        (Join-Path $PSScriptRoot '.venv\Scripts'),
        $pythonBase,
        (Join-Path $env:SystemRoot 'System32'),
        $env:SystemRoot,
        (Join-Path $env:SystemRoot 'System32\Wbem')
    ) -join ';'
    $env:TEMP = Join-Path $PSScriptRoot 'build\tmp'
    $env:TMP = $env:TEMP
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot 'build\pyinstaller-cache'
    New-Item -ItemType Directory -Path $env:TEMP, $env:PYINSTALLER_CONFIG_DIR -Force | Out-Null
    & $python -m PyInstaller .\StockTradingSim.spec --clean --noconfirm
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
}
finally {
    $env:PATH = $previousPath
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
    $env:PYINSTALLER_CONFIG_DIR = $previousCache
    Pop-Location
}
