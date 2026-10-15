# =====================================================================
# PC Remote Sentinel — USB Auto-Deploy Engine
# =====================================================================
# This script is triggered automatically by Windows Task Scheduler
# whenever a USB removable drive is inserted.
#
# It scans all removable drives for the PC-Remote-Sentinel installer
# and runs install.bat silently with admin privileges.
# =====================================================================

$LogFile = "C:\PCSentinel\usb_deploy.log"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $entry = "[$timestamp] $Message"
    try {
        if (-not (Test-Path (Split-Path $LogFile))) {
            New-Item -ItemType Directory -Path (Split-Path $LogFile) -Force | Out-Null
        }
        Add-Content -Path $LogFile -Value $entry -ErrorAction SilentlyContinue
    } catch { }
}

function Find-SentinelUSB {
    # Wait a moment for the drive to fully mount
    Start-Sleep -Seconds 3

    # Get all removable drives
    $removableDrives = Get-WmiObject Win32_LogicalDisk | Where-Object { $_.DriveType -eq 2 }

    foreach ($drive in $removableDrives) {
        $driveLetter = $drive.DeviceID  # e.g., "E:"
        $installerPath = Join-Path $driveLetter "install.bat"
        $markerFile = Join-Path $driveLetter "deploy_config.env"
        $agentFile = Join-Path $driveLetter "agent.py"

        # Verify this is a PC-Remote-Sentinel USB by checking for key files
        if ((Test-Path $installerPath) -and (Test-Path $markerFile) -and (Test-Path $agentFile)) {
            return $installerPath
        }
    }
    return $null
}

function Get-InstalledVersion {
    $versionFile = "C:\PCSentinel\.deploy_version"
    if (Test-Path $versionFile) {
        return (Get-Content $versionFile -Raw).Trim()
    }
    return ""
}

function Get-USBVersion {
    param([string]$USBRoot)
    $versionFile = Join-Path $USBRoot ".deploy_version"
    if (Test-Path $versionFile) {
        return (Get-Content $versionFile -Raw).Trim()
    }
    # If no version file, use hash of agent.py as version fingerprint
    $agentFile = Join-Path $USBRoot "agent.py"
    if (Test-Path $agentFile) {
        $hash = Get-FileHash $agentFile -Algorithm MD5
        return $hash.Hash.Substring(0, 12)
    }
    return "unknown"
}

# =====================================================================
# MAIN EXECUTION
# =====================================================================

Write-Log "USB insertion detected. Scanning for PC-Remote-Sentinel installer..."

$installerPath = Find-SentinelUSB

if (-not $installerPath) {
    Write-Log "No PC-Remote-Sentinel USB found on removable drives. Ignoring."
    exit 0
}

$usbRoot = Split-Path $installerPath
Write-Log "Found PC-Remote-Sentinel installer at: $installerPath"

# Check if already installed with same version (avoid redundant reinstalls)
$installedVersion = Get-InstalledVersion
$usbVersion = Get-USBVersion -USBRoot $usbRoot

if ($installedVersion -eq $usbVersion -and $installedVersion -ne "" -and $installedVersion -ne "unknown") {
    Write-Log "Already installed with matching version ($installedVersion). Skipping reinstall."
    exit 0
}

Write-Log "Proceeding with installation (USB version: $usbVersion, Installed: $installedVersion)..."

# Run install.bat silently with admin privileges
try {
    $process = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c `"$installerPath`" /SILENT" `
        -Verb RunAs `
        -WindowStyle Hidden `
        -PassThru `
        -Wait

    if ($process.ExitCode -eq 0) {
        Write-Log "Installation completed successfully (exit code 0)."
        # Save version marker
        if (-not (Test-Path "C:\PCSentinel")) {
            New-Item -ItemType Directory -Path "C:\PCSentinel" -Force | Out-Null
        }
        Set-Content -Path "C:\PCSentinel\.deploy_version" -Value $usbVersion
    } else {
        Write-Log "Installation finished with exit code: $($process.ExitCode)"
    }
} catch {
    Write-Log "ERROR launching installer: $_"
}

Write-Log "USB auto-deploy cycle complete."
