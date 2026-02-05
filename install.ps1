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

Write-Host "`n🚀 RokctAI Shared Workflows Installer`n" -ForegroundColor Cyan

# 1. Ensure .github/workflows exists
$targetPath = ".github/workflows"
if (!(Test-Path $targetPath)) {
    Write-Host "📁 Creating $targetPath..."
    New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
}

# 2. Download workflows
foreach ($wf in $vitalWorkflows) {
    $url = "$baseUrl/$workflowDir/$wf"
    $dest = Join-Path $targetPath $wf
    Write-Host "📥 Fetching $wf..."
    try {
        Invoke-WebRequest -Uri $url -OutFile $dest -ErrorAction Stop
    } catch {
        Write-Host "❌ Failed to download $wf: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# 3. Handle version.json
if (!(Test-Path "version.json")) {
    Write-Host "📝 Creating default version.json..." -ForegroundColor Yellow
    $versionJson = @{
        version = "0.0.1"
    } | ConvertTo-Json
    $versionJson | Out-File -FilePath "version.json" -Encoding utf8
} else {
    Write-Host "ℹ️ version.json already exists, skipping." -ForegroundColor Gray
}

Write-Host "`n✅ Installation Complete! Your repo is now part of the Rokct fleet.`n" -ForegroundColor Green
Write-Host "Next steps:" -ForegroundColor Gray
Write-Host "1. Check .github/workflows/release.yml to verify project_type." -ForegroundColor Gray
Write-Host "2. Commit and push the new workflows.`n" -ForegroundColor Gray
