param(
  [Parameter(Mandatory = $true)]
  [string]$PdfPath,

  [string]$OutDir = "",

  [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'

& "$PSScriptRoot\build.ps1" -PdfPath $PdfPath -OutDir $OutDir
& "$PSScriptRoot\serve-8000.ps1" -Port $Port
