# Open TCP 5174/8000 on Windows Firewall so colleagues on the same Wi-Fi can open the UI.
param(
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

function Get-LanIPv4 {
    $wlan = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.InterfaceAlias -match 'WLAN|Wi-?Fi|无线' -and $_.IPAddress -like '192.168.*' } |
        Select-Object -ExpandProperty IPAddress -First 1
    if ($wlan) { return $wlan }
    $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notmatch '^127\.' -and $_.IPAddress -notmatch '^169\.254\.' } |
        Select-Object -ExpandProperty IPAddress
    $pick = $ips | Where-Object { $_ -like '192.168.*' } | Select-Object -First 1
    if (-not $pick) { $pick = $ips | Where-Object { $_ -like '10.*' } | Select-Object -First 1 }
    if (-not $pick) { $pick = $ips | Select-Object -First 1 }
    return $pick
}

$admin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $admin) {
    if ($Quiet) { exit 0 }
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath
    ) -Wait
    exit $LASTEXITCODE
}

foreach ($port in 5174, 8000) {
    $name = "MOKA-VisionLab-$port"
    netsh advfirewall firewall delete rule name=$name | Out-Null
    netsh advfirewall firewall add rule name=$name dir=in action=allow protocol=TCP localport=$port profile=any | Out-Null
}

$ip = Get-LanIPv4
if (-not $ip) { $ip = "127.0.0.1" }
Write-Host ""
Write-Host "Firewall opened for 5174 and 8000."
Write-Host "Colleagues on this Wi-Fi:"
Write-Host "  http://${ip}:5174/login"
Write-Host "  admin / admin123"
Write-Host "Keep Backend and Frontend windows running on this PC."
Write-Host ""
if (-not $Quiet) { pause }
