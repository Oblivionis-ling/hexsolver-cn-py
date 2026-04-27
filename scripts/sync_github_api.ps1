param(
    [string]$Message = "",
    [string]$Token = $env:GITHUB_TOKEN
)

$ErrorActionPreference = "Stop"

if (-not $Token) {
    $Token = [Environment]::GetEnvironmentVariable("GITHUB_TOKEN", "User")
}
if (-not $Token) {
    throw "GITHUB_TOKEN is not set."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$remote = git remote get-url origin
if (-not $remote) {
    throw "origin remote is not configured."
}

if ($remote -notmatch 'github\.com[:/](?<owner>[^/]+)/(?<repo>[^/.]+)(\.git)?$') {
    throw "origin remote is not a GitHub repository: $remote"
}

$owner = $Matches.owner
$repo = $Matches.repo
$apiBase = "https://api.github.com/repos/$owner/$repo"
$headers = @{
    Authorization = "Bearer $Token"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

$localCommit = (git rev-parse --short HEAD).Trim()
if (-not $Message) {
    $Message = "Sync main from local commit $localCommit"
}

$entries = @()
$files = git -c core.quotePath=false ls-files
foreach ($file in $files) {
    $bytes = [System.IO.File]::ReadAllBytes((Join-Path $repoRoot $file))
    $content = [Convert]::ToBase64String($bytes)
    $blobBody = @{
        content = $content
        encoding = "base64"
    } | ConvertTo-Json
    $blob = Invoke-RestMethod -Method Post -Uri "$apiBase/git/blobs" -Headers $headers -Body $blobBody -ContentType "application/json"
    $entries += @{
        path = ($file -replace '\\', '/')
        mode = "100644"
        type = "blob"
        sha = $blob.sha
    }
}

$treeBody = @{ tree = $entries } | ConvertTo-Json -Depth 5
$tree = Invoke-RestMethod -Method Post -Uri "$apiBase/git/trees" -Headers $headers -Body $treeBody -ContentType "application/json"

$parents = @()
try {
    $ref = Invoke-RestMethod -Method Get -Uri "$apiBase/git/ref/heads/main" -Headers $headers
    if ($ref.object.sha) {
        $parents = @($ref.object.sha)
    }
} catch {
    $ref = $null
}

$commitBody = @{
    message = $Message
    tree = $tree.sha
    parents = $parents
} | ConvertTo-Json
$commit = Invoke-RestMethod -Method Post -Uri "$apiBase/git/commits" -Headers $headers -Body $commitBody -ContentType "application/json"

if ($null -eq $ref) {
    $refBody = @{
        ref = "refs/heads/main"
        sha = $commit.sha
    } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri "$apiBase/git/refs" -Headers $headers -Body $refBody -ContentType "application/json" | Out-Null
} else {
    $updateBody = @{
        sha = $commit.sha
        force = $false
    } | ConvertTo-Json
    Invoke-RestMethod -Method Patch -Uri "$apiBase/git/refs/heads/main" -Headers $headers -Body $updateBody -ContentType "application/json" | Out-Null
}

Write-Host "Synced via GitHub API: https://github.com/$owner/$repo/commit/$($commit.sha)"
