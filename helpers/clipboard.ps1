# Copy files to the clipboard (paste them in Explorer, chat or mail), or with -Image copy an image's pixels.
# Run with Windows PowerShell: powershell -NoProfile -STA -File clipboard.ps1 "<file>" ["<file>" ...] [-Image]
param([switch]$Image, [Parameter(Mandatory = $true, Position = 0, ValueFromRemainingArguments = $true)][string[]]$Path)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$full = @($Path | ForEach-Object { (Resolve-Path -LiteralPath $_).ProviderPath })
if ($Image) {
    $img = [System.Drawing.Image]::FromFile($full[0])
    try { [System.Windows.Forms.Clipboard]::SetImage($img) } finally { $img.Dispose() }
    "Copied the image $($full[0]) to the clipboard."
} else {
    $files = New-Object System.Collections.Specialized.StringCollection
    $full | ForEach-Object { [void]$files.Add($_) }
    [System.Windows.Forms.Clipboard]::SetFileDropList($files)
    "Copied $($full.Count) file(s) to the clipboard."
}
