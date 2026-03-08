# Autoresearch installer for Windows
$ErrorActionPreference = "Stop"
$pluginRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Installing claude-autoresearch..." -ForegroundColor Cyan

# Create venv if needed
if (-not (Test-Path "$pluginRoot\venv")) {
    Write-Host "Creating Python venv..."
    python -m venv "$pluginRoot\venv"
}

# Activate and install deps (none required for base — pure stdlib)
& "$pluginRoot\venv\Scripts\Activate.ps1"

# Register plugin in Claude Code settings
$claudeDir = "$env:USERPROFILE\.claude"
$settingsFile = "$claudeDir\settings.json"

if (Test-Path $settingsFile) {
    $settings = Get-Content $settingsFile | ConvertFrom-Json
} else {
    $settings = @{}
}

# Add MCP server config
$mcpFile = "$claudeDir\.mcp.json"
if (Test-Path $mcpFile) {
    $mcp = Get-Content $mcpFile -Raw | ConvertFrom-Json
} else {
    $mcp = @{ mcpServers = @{} }
}

$mcp.mcpServers | Add-Member -NotePropertyName "autoresearch" -NotePropertyValue @{
    command = "bash"
    args = @("run_server.sh")
    cwd = $pluginRoot
} -Force

$mcp | ConvertTo-Json -Depth 10 | Set-Content $mcpFile -Encoding UTF8

Write-Host "claude-autoresearch installed!" -ForegroundColor Green
Write-Host "MCP server registered. Restart Claude Code to activate." -ForegroundColor Yellow
