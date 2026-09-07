Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host "   NUCLEAR REMOTE PURGE: DISCARDING ALL 220+ OPEN PRS & BRANCHES" -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Fetch EVERY single open PR using a massive limit payload
Write-Host "Contacting GitHub API to pull all open pull requests..." -ForegroundColor Yellow
$prData = gh pr list --state open --limit 500 --json number,headRefName | ConvertFrom-Json

if (-not $prData) {
    Write-Host "[Success] No open pull requests found on the GitHub server." -ForegroundColor Green
    Exit
}

Write-Host "Found $($prData.Count) open pull requests to close.`n" -ForegroundColor Magenta

# 2. Iterate and destroy each remote element explicitly
foreach ($pr in $prData) {
    Write-Host "--------------------------------------------------------" -ForegroundColor Gray
    Write-Host "Processing PR #$($pr.number) on branch [$($pr.headRefName)]" -ForegroundColor White
    
    # Close the remote Pull Request
    Write-Host "Closing PR #$($pr.number)..."
    gh pr close $pr.number
    
    # Force delete the remote branch directly off the server
    if (-not [string]::IsNullOrEmpty($pr.headRefName)) {
        Write-Host "Deleting remote branch [origin/$($pr.headRefName)]..." -ForegroundColor Red
        git push origin --delete $pr.headRefName
    }
}

Write-Host "`n=============================================================" -ForegroundColor Green
Write-Host "Done! Syncing local environment metadata..." -ForegroundColor Green
git fetch --prune --all
