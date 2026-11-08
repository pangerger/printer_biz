# Run in Windows PowerShell on a PC with the official bizhub 185 driver installed.
# Exports two synthetic test jobs through that driver using PrintToFile.
param(
    [Parameter(Mandatory=$true)][string]$PrinterName,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
if (-not [System.Drawing.Printing.PrinterSettings]::InstalledPrinters.Contains($PrinterName)) {
    throw "Printer queue not found: $PrinterName"
}
if ($PrinterName -notmatch '(?i)185') {
    throw 'Use the queue configured with the official bizhub 185 driver.'
}
if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) {
    throw 'Provide an existing output directory on your approved external/network storage.'
}
foreach ($pattern in @('blank', 'markers')) {
    $path = Join-Path $OutputDirectory "bizhub185-$pattern.prn"
    if (Test-Path -LiteralPath $path) { throw "Refusing to overwrite: $path" }
    $doc = New-Object System.Drawing.Printing.PrintDocument
    $doc.PrinterSettings.PrinterName = $PrinterName
    if (-not $doc.PrinterSettings.IsValid) { throw 'Printer configuration invalid.' }
    $doc.DocumentName = "bizhub185-research-$pattern"
    $doc.PrinterSettings.Copies = 1
    $doc.PrinterSettings.PrintToFile = $true
    $doc.PrinterSettings.PrintFileName = $path
    $doc.PrintController = New-Object System.Drawing.Printing.StandardPrintController
    $a4 = $doc.PrinterSettings.PaperSizes | Where-Object { $_.Kind -eq 'A4' } | Select-Object -First 1
    if ($null -eq $a4) { throw 'Driver does not expose A4 paper.' }
    $doc.DefaultPageSettings.PaperSize = $a4
    $doc.DefaultPageSettings.Landscape = $false
    $handler = [System.Drawing.Printing.PrintPageEventHandler] {
        param($sender, $event)
        $event.Graphics.Clear([System.Drawing.Color]::White)
        $event.Graphics.PageUnit = [System.Drawing.GraphicsUnit]::Inch
        if ($pattern -eq 'markers') {
            $event.Graphics.FillRectangle([System.Drawing.Brushes]::Black, 0.5, 0.5, 1.0, 1.0)
            $event.Graphics.FillRectangle([System.Drawing.Brushes]::Black, 2.0, 0.5, 0.01, 2.0)
            $event.Graphics.FillRectangle([System.Drawing.Brushes]::Black, 0.5, 3.0, 3.0, 0.01)
        }
        $event.HasMorePages = $false
    }
    $doc.add_PrintPage($handler)
    try { $doc.Print() } finally { $doc.Dispose() }
    if (-not (Test-Path -LiteralPath $path) -or (Get-Item -LiteralPath $path).Length -eq 0) {
        throw 'Driver did not export a usable file. Inspect Windows print status before retrying.'
    }
    Get-FileHash -Algorithm SHA256 -LiteralPath $path
}
