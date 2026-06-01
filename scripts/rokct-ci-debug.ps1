# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "          ROKCT PLATFORM CI/CD - LOCAL WORKFLOW DRY-RUN WRAPPER" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

# 1. Audit Prerequisites
Write-Host "🔍 Auditing developer local toolchain..." -ForegroundColor Yellow

$dockerCheck = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCheck) {
    Write-Host "❌ ERROR: Docker CLI is not installed or not in PATH." -ForegroundColor Red
    Write-Host "👉 Get Docker: https://docs.docker.com/get-docker/" -ForegroundColor White
    Exit 1
}

& docker info > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ ERROR: Docker daemon is not running." -ForegroundColor Red
    Write-Host "👉 Please start Docker Desktop and try again." -ForegroundColor White
    Exit 1
}
Write-Host "✅ Docker daemon is running." -ForegroundColor Green

$actCheck = Get-Command act -ErrorAction SilentlyContinue
if (-not $actCheck) {
    Write-Host "❌ ERROR: Nektos 'act' is not installed." -ForegroundColor Red
    Write-Host "👉 Install 'act' on Windows (winget):" -ForegroundColor White
    Write-Host "   winget install nektos.act" -ForegroundColor Cyan
    Exit 1
}
Write-Host "✅ 'act' CLI is installed." -ForegroundColor Green

# 2. Select Workflow to Run
$workflowDir = ".github/workflows"
if (-not (Test-Path $workflowDir)) {
    Write-Host "❌ ERROR: Could not locate .github/workflows directory." -ForegroundColor Red
    Exit 1
}

$workflows = Get-ChildItem -Path $workflowDir -Filter "*.yml" -File | Sort-Object Name
if ($workflows.Count -eq 0) {
    Write-Host "❌ No workflows found in $workflowDir." -ForegroundColor Red
    Exit 1
}

Write-Host "`nSelect a workflow to dry-run locally:" -ForegroundColor Yellow
for ($i = 0; $i -lt $workflows.Count; $i++) {
    Write-Host "  [$i] $($workflows[$i].Name)" -ForegroundColor Cyan
}

Write-Host ""
$choice = Read-Host "Enter choice [0-$($workflows.Count - 1)]"

if ($choice -match '^\d+$') {
    $choiceInt = [int]$choice
    if ($choiceInt -ge 0 -and $choiceInt -lt $workflows.Count) {
        $chosenWorkflow = $workflows[$choiceInt].FullName
    } else {
        Write-Host "❌ Invalid choice range. Aborting." -ForegroundColor Red
        Exit 1
    }
} else {
    Write-Host "❌ Invalid choice syntax. Aborting." -ForegroundColor Red
    Exit 1
}

Write-Host "🚀 Selected: $(Split-Path $chosenWorkflow -Leaf)" -ForegroundColor Green

# 3. Setup Safe Mock Contexts
Write-Host "🔒 Creating temporary mock environments (.secrets.mock, .env.mock)..." -ForegroundColor Yellow
$secretsFile = ".secrets.mock"
$envFile = ".env.mock"

$secretsContent = @"
MONOREPO_PAT=mock_monorepo_pat_token
APP_ID=12345
APP_PRIVATE_KEY=mock_app_private_key_pem_file
COUNTER_API_KEY=mock_counter_api_key_badge
"@

$envContent = @"
GITHUB_ACTOR=RokctBOT
GITHUB_REPOSITORY=RokctAI/shared-workflows
GITHUB_EVENT_NAME=push
"@

Set-Content -Path $secretsFile -Value $secretsContent -Encoding utf8
Set-Content -Path $envFile -Value $envContent -Encoding utf8

# 4. Invoke Act
Write-Host "⚡ Executing local dry-run via act..." -ForegroundColor Yellow
Write-Host "--------------------------------------------------------------------------------" -ForegroundColor DarkGray

& act -W $chosenWorkflow --secret-file $secretsFile --env-file $envFile
$actExitCode = $LASTEXITCODE

Write-Host "--------------------------------------------------------------------------------" -ForegroundColor DarkGray

# 5. Clean up
Write-Host "🧹 Performing secure environment cleanup..." -ForegroundColor Yellow
if (Test-Path $secretsFile) { Remove-Item $secretsFile -Force }
if (Test-Path $envFile) { Remove-Item $envFile -Force }

if ($actExitCode -eq 0) {
    Write-Host "✅ Dry-run completed successfully!" -ForegroundColor Green
} else {
    Write-Host "❌ Dry-run execution failed. Inspect logs above for debug information." -ForegroundColor Red
}

Exit $actExitCode
