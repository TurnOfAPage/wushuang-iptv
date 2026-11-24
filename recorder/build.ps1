# 无双IPTV录像工具 · GUI 构建脚本（在 recorder 目录运行）
# 产物: ..\dist\无双IPTV录像工具\ (onedir 文件夹版 / 无控制台 / 不需要管理员 / 内嵌参考库)
# 注意：不用 --onefile！单文件 exe 启动时需向系统临时目录解包，会被火绒等安全软件拦截
# （报 "Could not create temporary directory!"）；onedir 无解包动作，天然免疫。
Set-Location $PSScriptRoot
$src = "$PSScriptRoot\..\src"
$extra = @()
if (Test-Path "$src\refdb.json.gz") {
    $extra += @('--add-data', "$src\refdb.json.gz;.")
}
python -m PyInstaller --noconfirm --onedir --noconsole `
  --name "无双IPTV录像工具" `
  --icon "$src\app.ico" `
  --add-data "$src\app.ico;." `
  --paths $src `
  @extra `
  --distpath "$PSScriptRoot\..\dist" `
  --workpath "$PSScriptRoot\..\build\recorder" `
  --specpath "$PSScriptRoot\..\build\recorder" `
  rec_main.py
Compress-Archive -Path "$PSScriptRoot\..\dist\无双IPTV录像工具" `
  -DestinationPath "$PSScriptRoot\..\dist\无双IPTV录像工具-win.zip" -Force
Write-Host "完成: $PSScriptRoot\..\dist\无双IPTV录像工具\无双IPTV录像工具.exe (+win.zip)"
