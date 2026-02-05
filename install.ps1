param (
    [string]$ProjectName = "smart",
    [switch]$LocalMode
)

# Set Console Encoding to UTF8 for clean icons
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Configuration
$baseUrl = "https://raw.githubusercontent.com/RokctAI/shared-workflows/main"
$workflowDir = "examples/workflows"
$vitalWorkflows = @(
    "build.yml", 
    "release.yml", 
    "security.yml", 
    "linter.yml", 
    "merge.yml", 
    "assign.yml", 
    "labeler.yml",
    "stale.yml",
    "todo.yml",
    "dependabot.yml"
)

# Default Values
$projectType = "smart"
$startingVersion = "0.0.1"
$releaseStrategy = "immediate"
$cronSchedule = "0 23 * * 5"
$nodeVersion = "24"
$pythonVersion = "3.14"

Write-Host "`n🚀 RokctAI Shared Workflows Installer`n" -ForegroundColor Cyan

# --- 1. Interaction ---
$customize = "n"
if ($null -eq $env:GITHUB_ACTIONS -or [Console]::IsInputRedirected) {
    try {
        $customize = Read-Host "Do you want to customize your workflow setup? (y/N - Press Enter for No)"
    }
    catch {
        $customize = "n"
    }
}

if ($customize -eq 'y' -or $customize -eq 'Y') {
    Write-Host "`n🛠️ Customizing Setup... (Press Enter to keep the [default] value)`n" -ForegroundColor Yellow
    
    # Project Type
    Write-Host "Select Project Type:"
    Write-Host "1. smart (Auto-detect Flutter/Node/Frappe)"
    Write-Host "2. flutter (Mobile/Desktop/Web)"
    Write-Host "3. frappe (ERPNext/Python)"
    Write-Host "4. node (Next.js/React/JS)"
    $choice = Read-Host "Choice [1]"
    switch ($choice) {
        "2" { $projectType = "flutter" }
        "3" { $projectType = "frappe" }
        "4" { $projectType = "node" }
        Default { $projectType = "smart" }
    }

    # Versioning (Skip for Flutter)
    if ($projectType -ne "flutter") {
        $startingVersionInput = Read-Host "Starting version [$startingVersion]"
        if (![string]::IsNullOrWhiteSpace($startingVersionInput)) { $startingVersion = $startingVersionInput }
    }

    # Release Strategy
    Write-Host "`nSelect Release Strategy:"
    Write-Host "1. immediate (Release on every push to main)"
    Write-Host "2. weekly (Promote Friday RCs to Stable)"
    Write-Host "3. weekly-rc (Pre-release RCs on every push to main)"
    $strategyChoice = Read-Host "Choice [1]"
    switch ($strategyChoice) {
        "2" { $releaseStrategy = "weekly" }
        "3" { $releaseStrategy = "weekly-rc" }
        Default { $releaseStrategy = "immediate" }
    }

    # Cron Schedule (Only for weekly)
    if ($releaseStrategy -like "weekly*") {
        $cronInput = Read-Host "Cron schedule [$cronSchedule] (e.g., '0 23 * * 5' for Friday 11PM)"
        if (![string]::IsNullOrWhiteSpace($cronInput)) { $cronSchedule = $cronInput }
    }

    # Dependency Versions
    Write-Host "`nDefault Dependency Versions:"
    $nodeVersionInput = Read-Host "Node.js version [$nodeVersion]"
    if (![string]::IsNullOrWhiteSpace($nodeVersionInput)) { $nodeVersion = $nodeVersionInput }
    
    $pythonVersionInput = Read-Host "Python version [$pythonVersion]"
    if (![string]::IsNullOrWhiteSpace($pythonVersionInput)) { $pythonVersion = $pythonVersionInput }
}
else {
    Write-Host "`n⏩ Using standard fleet defaults (Quick Install)." -ForegroundColor Gray
}

# --- 2. Preparing Files ---
$targetPath = ".github/workflows"
if (!(Test-Path $targetPath)) {
    Write-Host "`n📁 Creating $targetPath..."
    New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
}

# 3. Download and Patch
foreach ($wf in $vitalWorkflows) {
    if ($LocalMode) {
        $src = if ($wf -eq "dependabot.yml") { "../examples/$wf" } else { "../$workflowDir/$wf" }
        # Read as single string, ensure Unix line endings
        $content = (Get-Content $src -Raw) -replace "`r`n", "`n"
    }
    else {
        $url = if ($wf -eq "dependabot.yml") { "$baseUrl/examples/$wf" } else { "$baseUrl/$workflowDir/$wf" }
        Write-Host "📥 Fetching and Patching ${wf}..."
        try {
            $content = (Invoke-WebRequest -Uri $url -UseBasicParsing -ErrorAction Stop).Content
            $content = $content -replace "`r`n", "`n"
        }
        catch {
            Write-Host "❌ Failed to fetch ${wf}: $($_.Exception.Message)" -ForegroundColor Red
            continue
        }
    }

    $dest = if ($wf -eq "dependabot.yml") { Join-Path ".github" $wf } else { Join-Path $targetPath $wf }

    # Patching
    if ($wf -eq "build.yml" -or $wf -eq "release.yml") {
        # Project Type
        if ($projectType -ne "smart") {
            $content = $content -replace "project_type: '[^']+'", "project_type: '$projectType'"
        }
        # Strategy
        $content = $content -replace "release_strategy: '[^']+'", "release_strategy: '$releaseStrategy'"
        # Cron Schedule
        $content = $content -replace "cron: '[^']+'", "cron: '$cronSchedule'"
        # Node
        $content = $content -replace "(?s)(node-version:.*?default: )'[^']+'", "`${1}'$nodeVersion'"
        # Python
        $content = $content -replace "(?s)(python-version:.*?default: )'[^']+'", "`${1}'$pythonVersion'"
    }

    # Save file with UTF8 encoding (No BOM) and Unix-style line endings (LF)
    # Get physical path for WriteAllText
    $fullDest = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $dest))
    $dir = [System.IO.Path]::GetDirectoryName($fullDest)
    if (!(Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    
    [System.IO.File]::WriteAllText($fullDest, $content, (New-Object System.Text.UTF8Encoding $false))
}

# 4. Handle version.json (Skip for Flutter)
if ($projectType -ne "flutter") {
    if (!(Test-Path "version.json")) {
        Write-Host "`n📝 Creating version.json ($startingVersion)..." -ForegroundColor Yellow
        $json = @{ version = $startingVersion } | ConvertTo-Json -Compress
        $json | Set-Content -Path "version.json" -Encoding utf8
    }
}

Write-Host "`n✅ Installation Complete!" -ForegroundColor Green
