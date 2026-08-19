$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Py = "D:\Anaconda\envs\cv_python_tigerpro\python.exe"
if (-not (Test-Path $Py)) {
    $Py = "python"
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Creating backend/.venv with $Py"
    & $Py -m venv .venv
}

$VenvPy = ".\.venv\Scripts\python.exe"
& $VenvPy -m pip install -U pip
& $VenvPy -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
& $VenvPy -m pip install -r requirements.txt
Write-Host "venv ready: $VenvPy"
