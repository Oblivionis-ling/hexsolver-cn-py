$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path ".git")) {
    git init
    git branch -M main
}

$hookDir = Join-Path $repoRoot ".git\hooks"
New-Item -ItemType Directory -Force -Path $hookDir | Out-Null

$hookPath = Join-Path $hookDir "post-commit"
$hook = @'
#!/bin/sh
remote_url=$(git remote get-url origin 2>/dev/null)
if [ -z "$remote_url" ]; then
  echo "post-commit: origin remote is not configured; skip auto push."
  exit 0
fi

git push origin main
if [ $? -ne 0 ]; then
  echo "post-commit: git push failed; trying GitHub API sync fallback."
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync_github_api.ps1
  if [ $? -ne 0 ]; then
    echo "post-commit: API sync fallback failed. Run scripts/sync_github.ps1 after fixing network or auth."
  fi
fi
exit 0
'@

Set-Content -Path $hookPath -Value $hook -Encoding ASCII
Write-Host "Installed post-commit auto-push hook."
