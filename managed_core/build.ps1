$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$bin = Join-Path $root "bin"
New-Item -ItemType Directory -Force -Path $bin | Out-Null
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path -LiteralPath $csc)) {
    throw ".NET Framework C# compiler not found: $csc"
}

& $csc /nologo /target:library "/out:$bin\UnityEngine.dll" "$root\UnityEngineStub.cs"
if ($LASTEXITCODE -ne 0) { throw "UnityEngineStub build failed: $LASTEXITCODE" }

& $csc /nologo /target:library "/out:$bin\TextMeshPro-5.6-Runtime.dll" "/reference:$bin\UnityEngine.dll" "$root\TextMeshProStub.cs"
if ($LASTEXITCODE -ne 0) { throw "TextMeshProStub build failed: $LASTEXITCODE" }

& $csc /nologo "/out:$bin\HexcellsHeadless.exe" "/reference:$bin\UnityEngine.dll" "/reference:$bin\TextMeshPro-5.6-Runtime.dll" "$root\HexcellsHeadless.cs"
if ($LASTEXITCODE -ne 0) { throw "HexcellsHeadless build failed: $LASTEXITCODE" }

Write-Host "Easy headless managed core built: $bin"
