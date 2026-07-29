# rebuild_pgmc.ps1

$ErrorActionPreference = "Stop"

# Actual working repository: directory containing this script
$sourceRepo = $PSScriptRoot

# Temporary short-path compilation repository
$buildRepo = "C:\PGMcpp_work\PGMcpp"

$sourcePybindings = Join-Path $sourceRepo "pybindings"
$buildPybindings = Join-Path $buildRepo "pybindings"
$python = Join-Path $sourceRepo ".venv\Scripts\python.exe"
$pydPattern = "PGMcpp*.pyd"

Write-Host ""
Write-Host "===== PGMcpp rebuild started ====="
Write-Host "Source repository: $sourceRepo"
Write-Host "Build repository:  $buildRepo"
Write-Host "Python:             $python"
Write-Host ""

# ---------------------------------------------------------------------------
# Validate required folders and files
# ---------------------------------------------------------------------------

$requiredPaths = @(
    $python,
    (Join-Path $sourceRepo "header\Controller.h"),
    (Join-Path $sourceRepo "source\Controller.cpp"),
    (Join-Path $sourcePybindings "snippets\PYBIND11_Controller.cpp"),
    (Join-Path $buildRepo "header"),
    (Join-Path $buildRepo "source"),
    (Join-Path $buildPybindings "snippets"),
    (Join-Path $buildPybindings "setup.py")
)

foreach ($path in $requiredPaths) {
    if (-not (Test-Path $path)) {
        throw "Required path not found: $path"
    }
}

# ---------------------------------------------------------------------------
# Synchronize current source into temporary build repository
# ---------------------------------------------------------------------------

Write-Host "Copying current source into temporary build repository..."

Copy-Item `
    (Join-Path $sourceRepo "header\*") `
    (Join-Path $buildRepo "header") `
    -Recurse -Force

Copy-Item `
    (Join-Path $sourceRepo "source\*") `
    (Join-Path $buildRepo "source") `
    -Recurse -Force

Copy-Item `
    (Join-Path $sourcePybindings "snippets\*") `
    (Join-Path $buildPybindings "snippets") `
    -Recurse -Force

Copy-Item `
    (Join-Path $sourcePybindings "PYBIND11_PGM.cpp") `
    (Join-Path $buildPybindings "PYBIND11_PGM.cpp") `
    -Force

Copy-Item `
    (Join-Path $sourcePybindings "setup.py") `
    (Join-Path $buildPybindings "setup.py") `
    -Force

# Verify PSIS was transferred
$stagedControllerBinding =
    Join-Path $buildPybindings "snippets\PYBIND11_Controller.cpp"

if (-not (
    Select-String `
        -Path $stagedControllerBinding `
        -Pattern 'value\("PSIS"' `
        -Quiet
)) {
    throw "The staged Controller binding does not contain ControlMode::PSIS."
}

Write-Host "PSIS binding confirmed in temporary build repository."

# ---------------------------------------------------------------------------
# Remove cached build products
# ---------------------------------------------------------------------------

Write-Host "Removing previous build products..."

Remove-Item `
    (Join-Path $buildPybindings "build") `
    -Recurse -Force -ErrorAction SilentlyContinue

Get-ChildItem `
    -Path $buildPybindings `
    -Filter $pydPattern `
    -ErrorAction SilentlyContinue |
    Remove-Item -Force

# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------

Push-Location $buildPybindings

try {
    Write-Host ""
    Write-Host "Building Python bindings..."

    & $python setup.py build_ext --inplace --force

    if ($LASTEXITCODE -ne 0) {
        throw "Binding compilation failed with exit code $LASTEXITCODE."
    }

    $builtPyd = Get-ChildItem `
        -Path $buildPybindings `
        -Filter $pydPattern |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -eq $builtPyd) {
        throw "Compilation completed but no PGMcpp .pyd file was found."
    }

    Write-Host ""
    Write-Host "Testing temporary build..."

    & $python -c `
        "import sys; sys.path.insert(0, r'$buildPybindings'); import PGMcpp; print('Using:', PGMcpp.__file__); print(PGMcpp.ControlMode.PSIS)"

    if ($LASTEXITCODE -ne 0) {
        throw "Temporary binding import or PSIS verification failed."
    }

    # -----------------------------------------------------------------------
    # Copy validated binding into actual repository
    # -----------------------------------------------------------------------

    Write-Host ""
    Write-Host "Copying validated binding back to working repository..."

    Copy-Item `
        $builtPyd.FullName `
        (Join-Path $sourcePybindings $builtPyd.Name) `
        -Force
}
finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# Verify binding from actual repository
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Testing binding from working repository..."

& $python -c `
    "import sys; sys.path.insert(0, r'$sourcePybindings'); import PGMcpp; print('Using:', PGMcpp.__file__); print(PGMcpp.ControlMode.PSIS)"

if ($LASTEXITCODE -ne 0) {
    throw "Final working-repository import or PSIS verification failed."
}

Write-Host ""
Write-Host "BUILD SUCCESSFUL." -ForegroundColor Green
Write-Host "Finished: $(Get-Date)"
Write-Host "===== PGMcpp rebuild complete ====="
Write-Host ""