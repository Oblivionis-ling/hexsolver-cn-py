param(
    [string]$RepoName = "hexsolver-cn-py",
    [string]$Description = "Chinese Hexcells Infinite screenshot OCR and solver workbench.",
    [switch]$Public,
    [string]$Token = $env:GITHUB_TOKEN
)

$ErrorActionPreference = "Stop"

if (-not $Token) {
    Write-Host "GITHUB_TOKEN is not set. Create a token with repo permission, then run:"
    Write-Host '$env:GITHUB_TOKEN="ghp_xxx"'
    Write-Host ".\scripts\create_github_repo.ps1"
    exit 2
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$headers = @{
    Authorization = "Bearer $Token"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

$body = @{
    name = $RepoName
    description = $Description
    private = -not $Public
    auto_init = $false
} | ConvertTo-Json

try {
    $repo = Invoke-RestMethod -Method Post -Uri "https://api.github.com/user/repos" -Headers $headers -Body $body -ContentType "application/json"
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 422) {
        Write-Host "Repository may already exist. Fetching current user to configure remote..."
        $user = Invoke-RestMethod -Method Get -Uri "https://api.github.com/user" -Headers $headers
        $remoteUrl = "https://github.com/$($user.login)/$RepoName.git"
        $remoteNames = @(git remote)
        if ($remoteNames -contains "origin") {
            git remote remove origin
        }
        git remote add origin $remoteUrl
        Write-Host "Configured origin: $remoteUrl"
        exit 0
    }
    throw
}

$remoteNames = @(git remote)
if ($remoteNames -contains "origin") {
    git remote remove origin
}
git remote add origin $repo.clone_url
Write-Host "Created repository and configured origin: $($repo.clone_url)"
