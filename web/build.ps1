param(
  [Parameter(Mandatory = $true)]
  [string]$PdfPath,

  [string]$OutDir = ""
)

$ErrorActionPreference = 'Stop'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$structure = Join-Path $repoRoot 'site\report-structure.json'
$outDirResolved = if ($OutDir -and $OutDir.Trim()) { Resolve-Path $OutDir } else { $repoRoot }
$builder = Join-Path $PSScriptRoot 'build_redesigned_site.py'

if (-not (Test-Path $pythonExe)) {
  throw "Python venv not found at: $pythonExe"
}
if (-not (Test-Path $structure)) {
  throw "Missing structure file: $structure"
}
if (-not (Test-Path $builder)) {
  throw "Missing site generator: $builder"
}

& $pythonExe $builder --pdf $PdfPath --structure $structure --out $outDirResolved
