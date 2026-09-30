param(
    [Parameter(Mandatory = $true)]
    [string]$GatewayWs,

    [Parameter(Mandatory = $true)]
    [string]$AgentToken,

    [string]$AgentId = "octarin",
    [string]$AllowedRoots = "C:\hh-agent",
    [string]$InstallDir = "C:\ProgramData\MCP-RDC",
    [string]$SourceRoot = ""
)

$ErrorActionPreference = "Stop"

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [string[]]$Arguments = @()
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 surfaces native stderr as ErrorRecord objects.
        # Do not treat stderr alone as a terminating PowerShell error; trust the process exit code.
        $ErrorActionPreference = "Continue"
        & $FilePath @Arguments
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($exitCode -ne 0) {
        throw "$FilePath exited with code $exitCode"
    }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principalCheck = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principalCheck.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell."
}

if (-not $SourceRoot) {
    $SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    $pythonExe = "py"
    $pythonArgs = @("-3")
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $winget) {
            throw "Python 3.10+ is required and winget is unavailable."
        }
        Invoke-NativeCommand -FilePath $winget.Source -Arguments @(
            "install",
            "--id", "Python.Python.3.12",
            "--exact",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements"
        )
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) {
            throw "Python was installed but is not visible in PATH yet. Re-open PowerShell and rerun."
        }
    }
    $pythonExe = "python"
    $pythonArgs = @()
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$venv = Join-Path $InstallDir "venv"
Invoke-NativeCommand -FilePath $pythonExe -Arguments ($pythonArgs + @("-m", "venv", $venv))

$venvPython = Join-Path $venv "Scripts\python.exe"
Invoke-NativeCommand -FilePath $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
Invoke-NativeCommand -FilePath $venvPython -Arguments @("-m", "pip", "install", $SourceRoot)

$configPath = Join-Path $InstallDir "agent.env"
@"
MCP_RDC_GATEWAY_WS=$GatewayWs
MCP_RDC_AGENT_TOKEN=$AgentToken
MCP_RDC_AGENT_ID=$AgentId
MCP_RDC_ALLOWED_ROOTS=$AllowedRoots
MCP_RDC_COMMAND_TIMEOUT=120
MCP_RDC_MAX_OUTPUT_BYTES=1000000
"@ | Set-Content -Path $configPath -Encoding UTF8

$runScript = Join-Path $InstallDir "run-agent.ps1"
@'
$ErrorActionPreference = "Stop"
$configPath = Join-Path $PSScriptRoot "agent.env"
Get-Content $configPath | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2], "Process")
    }
}
& (Join-Path $PSScriptRoot "venv\Scripts\mcp-rdc-agent.exe")
'@ | Set-Content -Path $runScript -Encoding UTF8

$acl = Get-Acl $configPath
$acl.SetAccessRuleProtection($true, $false)
$adminsSid = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-32-544")
$systemSid = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-18")
$adminRule = New-Object System.Security.AccessControl.FileSystemAccessRule($adminsSid, "FullControl", "Allow")
$systemRule = New-Object System.Security.AccessControl.FileSystemAccessRule($systemSid, "FullControl", "Allow")
$acl.AddAccessRule($adminRule) | Out-Null
$acl.AddAccessRule($systemRule) | Out-Null
Set-Acl -Path $configPath -AclObject $acl

$taskName = "MCP-RDC Agent"
$actionArgs = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $runScript + '"'
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs
$trigger = New-ScheduledTaskTrigger -AtStartup
$taskPrincipal = New-ScheduledTaskPrincipal -UserId "S-1-5-18" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $taskPrincipal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName

Write-Host ""
Write-Host "MCP-RDC agent installed." -ForegroundColor Green
Write-Host "Task: $taskName"
Write-Host "Agent: $AgentId"
Write-Host "Allowed roots: $AllowedRoots"
Write-Host "Gateway: $GatewayWs"
