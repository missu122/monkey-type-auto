param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$ResolvedPath = (Resolve-Path -LiteralPath $ImagePath).Path

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.FileAccessMode, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]

$AsTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and
    $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($Operation, [Type]$ResultType) {
    $AsTask = $AsTaskGeneric.MakeGenericMethod($ResultType)
    $Task = $AsTask.Invoke($null, @($Operation))
    $Task.Wait() | Out-Null
    return $Task.Result
}

$File = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ResolvedPath)) ([Windows.Storage.StorageFile])
$Stream = Await ($File.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$Decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($Stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$Bitmap = Await ($Decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$BestText = ''
$BestScore = -1
$BestCyrillicText = ''
$BestCyrillicScore = -1

foreach ($Language in [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages) {
    $Engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($Language)
    if ($null -eq $Engine) {
        continue
    }

    $Result = Await ($Engine.RecognizeAsync($Bitmap)) ([Windows.Media.Ocr.OcrResult])
    $Text = [string]$Result.Text
    $Score = ($Text -replace '\s', '').Length
    $CyrillicScore = ([regex]::Matches($Text, '\p{IsCyrillic}')).Count

    if ($Score -gt $BestScore) {
        $BestScore = $Score
        $BestText = $Text
    }

    if ($CyrillicScore -gt $BestCyrillicScore) {
        $BestCyrillicScore = $CyrillicScore
        $BestCyrillicText = $Text
    }
}

if ($BestScore -lt 0) {
    throw 'Windows OCR is not available. Check Windows language packs.'
}

if ($BestCyrillicScore -ge 3) {
    $BestCyrillicText
} else {
    $BestText
}
