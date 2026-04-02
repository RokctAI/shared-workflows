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
$flutterVersion = "3.24.0"
$dependabotInterval = "monthly"
$ghHandle = "@RendaniSinyage"

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
        default { $projectType = "smart" }
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
        default { $releaseStrategy = "immediate" }
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

    $flutterVersionInput = Read-Host "Flutter version [$flutterVersion]"
    if (![string]::IsNullOrWhiteSpace($flutterVersionInput)) { $flutterVersion = $flutterVersionInput }

    # CODEOWNERS Handle
    $ghHandleInput = Read-Host "GitHub handle for CODEOWNERS [$ghHandle]"
    if (![string]::IsNullOrWhiteSpace($ghHandleInput)) { $ghHandle = $ghHandleInput }

    # Dependabot Frequency
    Write-Host "`nSelect Dependabot Update Frequency:"
    Write-Host "1. monthly (Fleet standard - Recommended)"
    Write-Host "2. weekly"
    Write-Host "3. daily"
    $depChoice = Read-Host "Choice [1]"
    switch ($depChoice) {
        "2" { $dependabotInterval = "weekly" }
        "3" { $dependabotInterval = "daily" }
        default { $dependabotInterval = "monthly" }
    }
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
        
        # Cron Exclusion for Flutter
        if ($wf -eq "release.yml" -and $projectType -eq "flutter") {
            Write-Host "🛡️ Removing Friday Cron for Flutter project..." -ForegroundColor Yellow
            $content = $content -replace "(?m)^  schedule:\n    - cron: '.*?'\n", ""
        }
        else {
            # Patch Cron Schedule (Only for non-flutter or if explicitly allowed)
            $content = $content -replace "cron: '[^']+'", "cron: '$cronSchedule'"
        }

        # Cron Schedule
        # Node
        $content = $content -replace "(?s)(node-version:.*?default: )'[^']+'", "`${1}'$nodeVersion'"
        # Python
        $content = $content -replace "(?s)(python-version:.*?default: )'[^']+'", "`${1}'$pythonVersion'"
        # Flutter
        $content = $content -replace "(?s)(flutter-version:.*?default: )'[^']+'", "`${1}'$flutterVersion'"
        # Smart Flutter Pin (for direct 'flutter-version: ...' lines if they exist in templates)
        $content = $content -replace "flutter-version: '[^']+'", "flutter-version: '$flutterVersion'"
    }

    # Dependabot Interval Patching
    if ($wf -eq "dependabot.yml") {
        if ($dependabotInterval -ne "monthly") {
            Write-Host "🛡️ Applying custom Dependabot frequency ($dependabotInterval) with safeguard..." -ForegroundColor Yellow
            $content = $content -replace 'interval: "monthly"', "interval: `"$dependabotInterval`" # rokct-keep"
        }
    }

    # Final normalization to LF and save with UTF8 (No BOM)
    # Full trim + single LF to match install.sh perfectly
    # 1. Strip BOM if present 2. Trim all whitespace 3. Add single LF 4. Normalize to LF
    $content = $content.TrimStart(@([char]0xfeff))
    $content = ($content.Trim() + "`n") -replace "`r`n", "`n"
    
    $fullDest = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $dest))
    $dir = [System.IO.Path]::GetDirectoryName($fullDest)
    if (!(Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    
    # Write as bytes to guarantee no BOM
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($content)
    [System.IO.File]::WriteAllBytes($fullDest, $bytes)
}

# 4. Handle version.json (Skip for Flutter)
if ($projectType -ne "flutter") {
    if (!(Test-Path "version.json")) {
        Write-Host "`n📝 Creating version.json ($startingVersion)..." -ForegroundColor Yellow
        $json = @{ version = $startingVersion } | ConvertTo-Json
        $json | Set-Content -Path "version.json" -Encoding utf8
    }
}

# 5. Handle CODEOWNERS (Governance - Custom Setup Only)
if ($customize -eq 'y' -or $customize -eq 'Y') {
    if (!(Test-Path ".github/CODEOWNERS")) {
        Write-Host "`n🛡️ Fetching and Patching .github/CODEOWNERS..." -ForegroundColor Yellow
        if (!(Test-Path ".github")) { New-Item -ItemType Directory -Path ".github" -Force | Out-Null }
        
        if ($LocalMode) {
            $src = "../examples/CODEOWNERS"
            $content = (Get-Content $src -Raw) -replace "`r`n", "`n"
        }
        else {
            $url = "$baseUrl/examples/CODEOWNERS"
            try {
                $content = (Invoke-WebRequest -Uri $url -UseBasicParsing -ErrorAction Stop).Content
                $content = $content -replace "`r`n", "`n"
            }
            catch {
                Write-Host "❌ Failed to fetch CODEOWNERS: $($_.Exception.Message)" -ForegroundColor Red
                $content = $null
            }
        }

        if ($null -ne $content) {
            $content = $content -replace "{{HANDLE}}", $ghHandle
            $fullDest = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) ".github/CODEOWNERS"))
            [System.IO.File]::WriteAllText($fullDest, $content, (New-Object System.Text.UTF8Encoding $false))
        }
    }
}

Write-Host "`n✅ Installation Complete!" -ForegroundColor Green

Write-Host "`n⚠️  IMPORTANT: GITHUB APP PERMISSIONS" -ForegroundColor Yellow
Write-Host "To allow the Fleet Standardizer to auto-fix and update your workflows, your GitHub App MUST have:"
Write-Host "  - Workflows: Read & Write" -ForegroundColor White
Write-Host "Otherwise, maintenance PRs will fail to push. Update this in your App Settings > Permissions & events.`n"
