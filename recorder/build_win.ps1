# 无双IPTV录像工具 · Windows 发行包构建（在 recorder 目录运行）
# 方案：官方签名 Python 运行时 + 应用脚本 + 微型启动器（onedir，不解包/不写保护目录）。
# 火绒/控制文件夹访问信任签名 python 子进程 → 下载目录默认可写、组播可收，杀软开着也能录。
# 产物: ..\dist\无双IPTV录像工具\ （含 GUI/CLI 两个启动器 exe + python\ + app\）与 -win.zip
Set-Location $PSScriptRoot
$root = "$PSScriptRoot\.."
$out = "$root\dist\无双IPTV录像工具"
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force -Path $out | Out-Null

$ver = python -c "import sys;print('.'.join(map(str,sys.version_info[:3])))"
$tag = python -c "import sys;print('%d%d'%sys.version_info[:2])"
$prefix = python -c "import sys;print(sys.base_prefix)"
Write-Host "Python $ver (tag $tag) from $prefix"

# ---- 1) 官方 embeddable 运行时（签名 python.exe/pythonw.exe）----
$zipUrl = "https://www.python.org/ftp/python/$ver/python-$ver-embed-amd64.zip"
$zipPath = "$root\build\pyembed.zip"
try {
    Invoke-WebRequest -UseBasicParsing -Uri $zipUrl -OutFile $zipPath -TimeoutSec 120
} catch {
    Write-Host "下载 embeddable 失败: $_"
    exit 1
}
Expand-Archive -Path $zipPath -DestinationPath "$out\python" -Force
# ---- 2) tkinter overlay（embeddable 不含 Tk；从本机同版本安装复制）----
New-Item -ItemType Directory -Force -Path "$out\python\Lib\site-packages" | Out-Null
Copy-Item "$prefix\Lib\tkinter" "$out\python\Lib\site-packages\tkinter" -Recurse -Force
Copy-Item "$prefix\DLLs\_tkinter.pyd" "$out\python\_tkinter.pyd" -Force
Copy-Item "$prefix\DLLs\*.dll" "$out\python\" -Force
Copy-Item "$prefix\tcl\tcl8.6" "$out\python\tcl8.6" -Recurse -Force
Copy-Item "$prefix\tcl\tk8.6" "$out\python\tk8.6" -Recurse -Force
Set-Content -Path "$out\python\python$tag._pth" -Value "python$tag.zip`r`n.`r`nLib\site-packages" -Encoding ASCII
# ---- 3) 应用代码 ----
New-Item -ItemType Directory -Force -Path "$out\app\src", "$out\app\recorder" | Out-Null
$mods = @('channeldb.py', 'epg.py', 'm3u.py', 'netutil.py', 'proxy.py', 'record.py',
          'tsutil.py', 'webui.py', 'verify.py')
foreach ($m in $mods) { Copy-Item "$root\src\$m" "$out\app\src\$m" }
if (Test-Path "$root\src\refdb.json.gz") { Copy-Item "$root\src\refdb.json.gz" "$out\app\src\refdb.json.gz" }
Copy-Item "$PSScriptRoot\rec_main.py", "$PSScriptRoot\rec_cli.py", "$PSScriptRoot\recinfo.py" "$out\app\recorder\"
# ---- 4) 入口（全信任进程链；无任何未签名 exe；入口文件纯 ASCII）----
Copy-Item "$PSScriptRoot\launcher_gui.vbs" "$out\recorder_gui.vbs" -Force
Copy-Item "$PSScriptRoot\launcher_cli.bat" "$out\recorder_cli.bat" -Force
Copy-Item "$PSScriptRoot\launch_gui.bat" "$out\launch_gui.bat" -Force
Copy-Item "$PSScriptRoot\launch_gui.bat" "$out\无双IPTV录像工具.bat" -Force
Copy-Item "$PSScriptRoot\launcher_gui.pyw" "$out\无双IPTV录像工具.pyw" -Force
Copy-Item "$PSScriptRoot\win_readme.txt" "$out\使用说明.txt" -Force
Copy-Item "$root\src\app.ico" "$out\app.ico" -Force
# ---- 5) 打包 ----
Compress-Archive -Path $out -DestinationPath "$root\dist\无双IPTV录像工具-win.zip" -Force
Write-Host "完成: $out （GUI: 无双IPTV录像工具.exe / CLI: WushuangIPTV-Recorder-CLI.exe）+ win.zip"
