# 无双IPTV录像工具 · CLI 构建脚本（在 recorder 目录运行）
# 产物: ..\dist\WushuangIPTV-Recorder-CLI\ (onedir 文件夹版 / 控制台 / 不需要管理员)
# 不用 --onefile：单文件解包到系统临时目录会被火绒等拦截（Could not create temporary directory!）
Set-Location $PSScriptRoot
$src = "$PSScriptRoot\..\src"
$extra = @()
if (Test-Path "$src\refdb.json.gz") {
    $extra += @('--add-data', "$src\refdb.json.gz;.")
}
python -m PyInstaller --noconfirm --onedir --console `
  --name "WushuangIPTV-Recorder-CLI" `
  --icon "$src\app.ico" `
  --paths $src `
  @extra `
  --distpath "$PSScriptRoot\..\dist" `
  --workpath "$PSScriptRoot\..\build\recorder" `
  --specpath "$PSScriptRoot\..\build\recorder" `
  rec_cli.py
Compress-Archive -Path "$PSScriptRoot\..\dist\WushuangIPTV-Recorder-CLI" `
  -DestinationPath "$PSScriptRoot\..\dist\WushuangIPTV-Recorder-CLI-win.zip" -Force
Write-Host "完成: $PSScriptRoot\..\dist\WushuangIPTV-Recorder-CLI\WushuangIPTV-Recorder-CLI.exe (+win.zip)"
