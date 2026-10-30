# Build Vectorizer.exe onedir + zip (must run on Windows).
$ErrorActionPreference = "Stop"
if (-not $IsWindows -and $env:OS -ne "Windows_NT") {
    Write-Error "Windows EXE builds require Windows (PyInstaller cannot cross-compile)."
}

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    python -m venv .venv
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -e ".[dev,packaging]"
& $Python (Join-Path $Root "scripts\make-ico.py")

$Version = & $Python -c "import pathlib,re; t=pathlib.Path('src/vectorizer/__init__.py').read_text(encoding='utf-8'); print(re.search(r'__version__\s*=\s*[\"']([^\"']+)', t).group(1))"
$Dist = Join-Path $Root "dist"
$Build = Join-Path $Root "build"
$AppDir = Join-Path $Dist "Vectorizer"
$ZipName = "Vectorizer-$Version-windows-x64.zip"
$ZipPath = Join-Path $Dist $ZipName
$Spec = Join-Path $Root "packaging\windows\vectorizer.spec"

if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir }
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }

& $Python -m PyInstaller --noconfirm --clean --distpath $Dist --workpath $Build $Spec

if (-not (Test-Path (Join-Path $AppDir "Vectorizer.exe"))) {
    Write-Error "Expected EXE missing: $AppDir\Vectorizer.exe"
}

Compress-Archive -Path $AppDir -DestinationPath $ZipPath -Force
Get-Item $ZipPath | Format-List FullName, Length
Write-Host "Unzip and run Vectorizer.exe"
