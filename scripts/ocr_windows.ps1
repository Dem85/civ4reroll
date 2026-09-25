param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath,

    [string]$Language = "ru-RU"
)

# =============================================================================
# OCR через встроенный в Windows 10/11 движок Windows.Media.Ocr.
# Не требует установки Tesseract и сторонних пакетов — только PowerShell 5.1+.
#
# Использование:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ocr_windows.ps1 ^
#       -ImagePath C:\path\to\shot.png -Language ru-RU
#
# Выводит распознанный текст в stdout (UTF-8).
# =============================================================================

$ErrorActionPreference = "Stop"

# WinRT StorageFile требует АБСОЛЮТНЫЙ путь (с буквой диска).
$ImagePath = [System.IO.Path]::GetFullPath($ImagePath)

if (-not (Test-Path -LiteralPath $ImagePath -PathType Leaf)) {
    throw "Файл изображения не найден: $ImagePath"
}

Add-Type -AssemblyName System.Runtime.WindowsRuntime

# Загрузка WinRT-типов (проекция Windows Runtime в .NET Framework / PS 5.1).
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.FileAccessMode, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]

# Прокладка: IAsyncOperation<T> -> System.Threading.Tasks.Task<T> (AsTask).
$asTaskGeneric = (
    [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq 'AsTask' -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    }
)[0]

function Await([object]$WinRtTask, [Type]$ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    try {
        $netTask.Wait(-1) | Out-Null
    } catch {
        # ToString() агрегатного исключения раскрывает все внутренние ошибки.
        throw "WinRT-операция не выполнена: $($_.Exception.ToString())"
    }
    $netTask.Result
}

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

# Windows OCR не принимает картинки больше MaxImageDimension (обычно 2600px).
$maxDim = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension
if ($bitmap.PixelWidth -gt $maxDim -or $bitmap.PixelHeight -gt $maxDim) {
    throw ("Изображение слишком большое ({0}x{1}), максимум {2}px. " +
           "Уменьшите его перед вызовом (например, в Python через Pillow).") -f `
        $bitmap.PixelWidth, $bitmap.PixelHeight, $maxDim
}

# Движок: сначала конкретный язык, затем языки профиля пользователя.
$lang = New-Object Windows.Globalization.Language $Language
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if ($null -eq $engine) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}
if ($null -eq $engine) {
    throw "Нет доступного OCR-движка Windows. Установите языковой пакет '$Language' (Параметры -> Время и язык -> Язык и регион)."
}

$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

# Текст выводим в UTF-8, чтобы русские буквы корректно доходили до Python.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
Write-Output $result.Text