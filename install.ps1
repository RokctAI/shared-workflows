param (
    [string]$ProjectName = "smart"
)

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
    "todo.yml"
)

# Default Values
$projectType = "smart"
$startingVersion = "0.0.1"
$releaseStrategy = "immediate"
$nodeVersion = "24"
$pythonVersion = "3.14"

Write-Host "`n🚀 RokctAI Shared Workflows Installer`n" -ForegroundColor Cyan

# --- 1. Interaction ---
$customize = Read-Host "Do you want to customize your workflow setup? (y/N)"
if ($customize -eq 'y' -or $customize -eq 'Y') {
    Write-Host "`n🛠️ Customizing Setup..." -ForegroundColor Yellow
    
    # Project Type
    Write-Host "`nSelect Project Type:"
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
        $startingVersion = Read-Host "Starting version [$startingVersion]"
        if ([string]::IsNullOrWhiteSpace($startingVersion)) { $startingVersion = "0.0.1" }
    }

    # Release Strategy
    Write-Host "`nSelect Release Strategy:"
    Write-Host "1. immediate (Release on every push to main - Default)"
    Write-Host "2. weekly (Promote Friday RCs to Stable)"
    Write-Host "3. weekly-rc (Pre-release RCs on every push to main)"
    $choice = Read-Host "Choice [1]"
    switch ($choice) {
        "2" { $releaseStrategy = "weekly" }
        "3" { $releaseStrategy = "weekly-rc" }
        Default { $releaseStrategy = "immediate" }
    }

    # Dependency Versions
    Write-Host "`nDefault Dependency Versions:"
    $nodeVersionInput = Read-Host "Node.js version [$nodeVersion]"
    if (![string]::IsNullOrWhiteSpace($nodeVersionInput)) { $nodeVersion = $nodeVersionInput }
    
    $pythonVersionInput = Read-Host "Python version [$pythonVersion]"
    if (![string]::IsNullOrWhiteSpace($pythonVersionInput)) { $pythonVersion = $pythonVersionInput }
}
else {
    Write-Host "`n⏩ Using standard fleet defaults (Standard Installation)." -ForegroundColor Gray
}

# --- 2. Preparing Files ---
$targetPath = ".github/workflows"
if (!(Test-Path $targetPath)) {
    Write-Host "`n📁 Creating $targetPath..."
    New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
}

# 3. Download and Patch
foreach ($wf in $vitalWorkflows) {
    $url = "$baseUrl/$workflowDir/$wf"
    $dest = Join-Path $targetPath $wf
    Write-Host "📥 Fetching and Patching $wf..."
    try {
        $content = (Invoke-WebRequest -Uri $url -UseBasicParsing -ErrorAction Stop).Content
        
        # Patching (Simple string replacements)
        if ($wf -eq "build.yml" -or $wf -eq "release.yml") {
            # Project Type
            if ($projectType -ne "smart") {
                $content = $content -replace "project_type: .*#", "project_type: '$projectType' #"
                $content = $content -replace "project_type: .*", "project_type: '$projectType'"
            }
            # Strategy
            $content = $content -replace "release_strategy: '.*'", "release_strategy: '$releaseStrategy'"
            # Node
            $content = $content -replace "node-version:.*default: '.*'", "node-version:`r`n        type: string`r`n        default: '$nodeVersion'"
            # Python
            $content = $content -replace "python-version:.*default: '.*'", "python-version:`r`n        type: string`r`n        default: '$pythonVersion'"
        }

        # Keep encoding consistent
        [System.IO.File]::WriteAllText((Get-Item -Path $dest -ErrorAction SilentlyContinue).FullName, $content, (New-Object System.Text.UTF8Encoding $false))
        if (!(Test-Path $dest)) {
            $content | Set-Content -Path $dest -Encoding utf8
        }
    }
    catch {
        Write-Host "❌ Failed to process $wf: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# 4. Handle version.json (Skip for Flutter)
if ($projectType -ne "flutter") {
    if (!(Test-Path "version.json")) {
        Write-Host "`n📝 Creating version.json ($startingVersion)..." -ForegroundColor Yellow
        $json = @{ version = $startingVersion } | ConvertTo-Json
        $json | Set-Content -Path "version.json" -Encoding utf8
    }
}

Write-Host "`n✅ Installation Complete! Your repo is now part of the Rokct fleet.`n" -ForegroundColor Green
Write-Host "Next steps:" -ForegroundColor Gray
Write-Host "1. Verify .github/workflows for your customized settings." -ForegroundColor Gray
Write-Host "2. Commit and push the new workflows.`n" -ForegroundColor Gray
