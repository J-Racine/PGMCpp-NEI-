# rebuild_pgmc.ps1

$repo = "C:\PGMcpp_work\PGMcpp"
$pybindings = "$repo\pybindings"
$pydPattern = "PGMcpp*.pyd"

Write-Host ""
Write-Host "===== PGMcpp rebuild started ====="
Write-Host "Time: $(Get-Date)"
Write-Host ""

cd $pybindings

Write-Host "Before rebuild:"
Get-ChildItem -Filter $pydPattern |
    Select-Object Name, LastWriteTime, Length |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Building pybindings..."
python setup.py build_ext --inplace

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "BUILD FAILED." -ForegroundColor Red
    Write-Host "Exit code: $LASTEXITCODE"
    cd $repo
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "After rebuild:"
Get-ChildItem -Filter $pydPattern |
    Select-Object Name, LastWriteTime, Length |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Testing import..."
python -c "import PGMcpp; print('Using:', PGMcpp.__file__)"

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "IMPORT TEST FAILED." -ForegroundColor Red
    cd $repo
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "BUILD SUCCESSFUL." -ForegroundColor Green
Write-Host "Finished: $(Get-Date)"
Write-Host "===== PGMcpp rebuild complete ====="
Write-Host ""

cd $repo