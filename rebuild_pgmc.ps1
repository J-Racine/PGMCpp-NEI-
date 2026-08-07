# rebuild_pgmc.ps1

$ErrorActionPreference = "Stop"

# ============================================================
# PATHS
# ============================================================

$sourceRepo = $PSScriptRoot
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

# ============================================================
# VALIDATE SOURCE REPOSITORY
# ============================================================

$requiredPaths = @(
    $python,
    (Join-Path $sourceRepo "header\Controller.h"),
    (Join-Path $sourceRepo "source\Controller.cpp"),
    (Join-Path $sourceRepo "header\Storage\Storage.h"),
    (Join-Path $sourceRepo "header\Storage\LiIon.h"),
    (Join-Path $sourceRepo "source\Storage\Storage.cpp"),
    (Join-Path $sourceRepo "source\Storage\LiIon.cpp"),
    (Join-Path $sourceRepo "third_party"),
    (Join-Path $sourcePybindings "snippets\PYBIND11_Controller.cpp"),
    (Join-Path $sourcePybindings "PYBIND11_PGM.cpp"),
    (Join-Path $sourcePybindings "setup.py")
)

Write-Host "Checking required source files..."

foreach ($path in $requiredPaths) {
    if (-not (Test-Path $path)) {
        throw "Required path not found: $path"
    }
}

Write-Host "Required source files confirmed."

# ============================================================
# VERIFY OUR BATTERY MODIFICATIONS
# ============================================================

$sourceLiIonHeader = Join-Path $sourceRepo "header\Storage\LiIon.h"
$sourceLiIonCpp = Join-Path $sourceRepo "source\Storage\LiIon.cpp"
$sourceStorageHeader = Join-Path $sourceRepo "header\Storage\Storage.h"
$sourceControllerCpp = Join-Path $sourceRepo "source\Controller.cpp"

if (-not (Select-String -Path $sourceLiIonHeader -SimpleMatch -Pattern '2.82233e6' -Quiet)) {
    throw "Modified LiIon degradation calibration (2.82233e6) was not found."
}

if (-not (Select-String -Path $sourceLiIonCpp -SimpleMatch -Pattern 'getCurrentEnergyCapacitykWh' -Quiet)) {
    throw "Dynamic LiIon energy-capacity code was not found."
}

if (-not (Select-String -Path $sourceStorageHeader -SimpleMatch -Pattern 'getCurrentEnergyCapacitykWh' -Quiet)) {
    throw "Storage current-energy-capacity method was not found."
}

if (-not (Select-String -Path $sourceControllerCpp -SimpleMatch -Pattern 'getCurrentEnergyCapacitykWh' -Quiet)) {
    throw "Controller dynamic-capacity SOC code was not found."
}

Write-Host "Modified SOH/SOC source confirmed."

# ============================================================
# CREATE TEMPORARY BUILD TREE
# ============================================================

Write-Host ""
Write-Host "Preparing temporary build repository..."

$buildDirectories = @(
    $buildRepo,
    (Join-Path $buildRepo "header"),
    (Join-Path $buildRepo "source"),
    (Join-Path $buildRepo "third_party"),
    $buildPybindings,
    (Join-Path $buildPybindings "snippets")
)

foreach ($directory in $buildDirectories) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

Write-Host "Temporary build directories ready."

# ============================================================
# COPY CURRENT SOURCE TO SHORT BUILD PATH
# ============================================================

Write-Host ""
Write-Host "Copying current source into temporary build repository..."

Copy-Item -Path (Join-Path $sourceRepo "header\*") -Destination (Join-Path $buildRepo "header") -Recurse -Force
Copy-Item -Path (Join-Path $sourceRepo "source\*") -Destination (Join-Path $buildRepo "source") -Recurse -Force
Copy-Item -Path (Join-Path $sourceRepo "third_party\*") -Destination (Join-Path $buildRepo "third_party") -Recurse -Force

Copy-Item -Path (Join-Path $sourcePybindings "snippets\*") -Destination (Join-Path $buildPybindings "snippets") -Recurse -Force
Copy-Item -Path (Join-Path $sourcePybindings "PYBIND11_PGM.cpp") -Destination (Join-Path $buildPybindings "PYBIND11_PGM.cpp") -Force
Copy-Item -Path (Join-Path $sourcePybindings "setup.py") -Destination (Join-Path $buildPybindings "setup.py") -Force

Write-Host "Source synchronization complete."

# ============================================================
# VERIFY STAGED SOURCE
# ============================================================

$stagedControllerBinding = Join-Path $buildPybindings "snippets\PYBIND11_Controller.cpp"
$stagedLiIonHeader = Join-Path $buildRepo "header\Storage\LiIon.h"
$stagedLiIonCpp = Join-Path $buildRepo "source\Storage\LiIon.cpp"
$stagedStorageHeader = Join-Path $buildRepo "header\Storage\Storage.h"
$stagedControllerCpp = Join-Path $buildRepo "source\Controller.cpp"

if (-not (Select-String -Path $stagedControllerBinding -SimpleMatch -Pattern 'value("PSIS"' -Quiet)) {
    throw "The staged Controller binding does not contain ControlMode::PSIS."
}

if (-not (Select-String -Path $stagedLiIonHeader -SimpleMatch -Pattern '2.82233e6' -Quiet)) {
    throw "Modified LiIon degradation calibration was not transferred."
}

if (-not (Select-String -Path $stagedLiIonCpp -SimpleMatch -Pattern 'getCurrentEnergyCapacitykWh' -Quiet)) {
    throw "Modified LiIon.cpp was not transferred."
}

if (-not (Select-String -Path $stagedStorageHeader -SimpleMatch -Pattern 'getCurrentEnergyCapacitykWh' -Quiet)) {
    throw "Modified Storage.h was not transferred."
}

if (-not (Select-String -Path $stagedControllerCpp -SimpleMatch -Pattern 'getCurrentEnergyCapacitykWh' -Quiet)) {
    throw "Modified Controller.cpp was not transferred."
}

Write-Host "Staged PSIS and SOH/SOC modifications confirmed."

# ============================================================
# REMOVE OLD TEMPORARY BUILD PRODUCTS
# ============================================================

Write-Host ""
Write-Host "Removing previous build products..."

Remove-Item -Path (Join-Path $buildPybindings "build") -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $buildPybindings -Filter $pydPattern -ErrorAction SilentlyContinue | Remove-Item -Force

# ============================================================
# COMPILE
# ============================================================

Push-Location $buildPybindings

try {
    Write-Host ""
    Write-Host "Building Python bindings..."

    & $python setup.py build_ext --inplace --force

    if ($LASTEXITCODE -ne 0) {
        throw "Binding compilation failed with exit code $LASTEXITCODE."
    }

    $builtPyd = Get-ChildItem -Path $buildPybindings -Filter $pydPattern |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -eq $builtPyd) {
        throw "Compilation completed but no PGMcpp .pyd file was found."
    }

    # ========================================================
    # TEST TEMPORARY BUILD
    # ========================================================

    Write-Host ""
    Write-Host "Testing temporary build..."

    & $python -c "import sys; sys.path.insert(0, r'$buildPybindings'); import PGMcpp; print('Using:', PGMcpp.__file__); print('Controller:', PGMcpp.ControlMode.PSIS)"

    if ($LASTEXITCODE -ne 0) {
        throw "Temporary binding import or PSIS verification failed."
    }

    # ========================================================
    # COPY VALIDATED BINDING BACK
    # ========================================================

    Write-Host ""
    Write-Host "Copying validated binding back to working repository..."

    Copy-Item -Path $builtPyd.FullName -Destination (Join-Path $sourcePybindings $builtPyd.Name) -Force
}
finally {
    Pop-Location
}

# ============================================================
# VERIFY WORKING REPOSITORY BINDING
# ============================================================

Write-Host ""
Write-Host "Testing binding from working repository..."

& $python -c "import sys; sys.path.insert(0, r'$sourcePybindings'); import PGMcpp; print('Using:', PGMcpp.__file__); print('Controller:', PGMcpp.ControlMode.PSIS)"

if ($LASTEXITCODE -ne 0) {
    throw "Final working-repository import or PSIS verification failed."
}

Write-Host ""
Write-Host "BUILD SUCCESSFUL." -ForegroundColor Green
Write-Host "Finished: $(Get-Date)"
Write-Host "===== PGMcpp rebuild complete ====="
Write-Host ""

