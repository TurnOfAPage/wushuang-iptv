# 无双IPTV · CLI 公开构建脚本（在 src 目录运行）
# 产物: ..\dist\无双IPTV-CLI.exe (单文件 / 控制台 / 不强制管理员；仅 capture 子命令需要管理员)
Set-Location $PSScriptRoot

# 可选：仅当已抓取社区参考数据时才内嵌参考库；默认不内嵌（运行时在线更新）
if (Test-Path "$PSScriptRoot\..\ref\national") {
    python build_refdb.py
}
$extra = @()
if (Test-Path "$PSScriptRoot\refdb.json.gz") {
    $extra += @('--add-data', "$PSScriptRoot\refdb.json.gz;.")
}

python -m PyInstaller --noconfirm --onefile --console `
  --name "无双IPTV-CLI" `
  --icon "$PSScriptRoot\app.ico" `
  @extra `
  --distpath "$PSScriptRoot\..\dist" `
  --workpath "$PSScriptRoot\..\build" `
  --specpath "$PSScriptRoot\..\build" `
  cli_entry.py
Write-Host "完成: $PSScriptRoot\..\dist\无双IPTV-CLI.exe"
