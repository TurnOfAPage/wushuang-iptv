# 无双IPTV录像工具 · Docker 部署包打包脚本（在 recorder 目录运行）
# 产物: ..\dist\docker-recorder\ （自包含上传目录：Dockerfile/compose/.env.example/README + 所需源码）
# 可选: ..\dist\iptv-recorder-1.0.0.tar （本机 Docker 可用时构建并导出离线镜像）
Set-Location $PSScriptRoot
$root = "$PSScriptRoot\.."
$out = "$root\dist\docker-recorder"
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force -Path "$out\src", "$out\recorder" | Out-Null

# CLI 运行所需核心模块（零第三方依赖；GUI/抓包模块不入镜像）
$mods = @('channeldb.py', 'epg.py', 'm3u.py', 'netutil.py', 'proxy.py', 'record.py', 'tsutil.py', 'webui.py')
foreach ($m in $mods) { Copy-Item "$root\src\$m" "$out\src\$m" }
if (Test-Path "$root\src\refdb.json.gz") { Copy-Item "$root\src\refdb.json.gz" "$out\src\refdb.json.gz" }
Copy-Item "$PSScriptRoot\rec_cli.py" "$out\recorder\rec_cli.py"
Copy-Item "$PSScriptRoot\recinfo.py" "$out\recorder\recinfo.py"
Copy-Item "$PSScriptRoot\docker\Dockerfile" "$out\Dockerfile"
Copy-Item "$PSScriptRoot\docker\entrypoint.sh" "$out\entrypoint.sh"
Copy-Item "$PSScriptRoot\docker\docker-compose.yml" "$out\docker-compose.yml"
Copy-Item "$PSScriptRoot\docker\.env.example" "$out\.env.example"
Copy-Item "$PSScriptRoot\docker\README.md" "$out\README.md"
Write-Host "打包完成: $out"

# 本机 Docker 守护进程可用时：构建 linux 镜像 + 冒烟 + 导出离线 tar
$daemon = docker info --format '{{.ServerVersion}}' 2>$null
if ($LASTEXITCODE -eq 0 -and $daemon) {
    docker build -t iptv-recorder:1.0.0 $out
    if ($LASTEXITCODE -eq 0) {
        docker run --rm iptv-recorder:1.0.0 info | Out-Null
        if ($LASTEXITCODE -eq 0) {
            docker save -o "$root\dist\iptv-recorder-1.0.0.tar" iptv-recorder:1.0.0
            Write-Host "镜像导出: $root\dist\iptv-recorder-1.0.0.tar"
        } else { Write-Host '镜像冒烟失败，未导出 tar' }
    } else { Write-Host '镜像构建失败，未导出 tar' }
} else {
    Write-Host 'Docker 守护进程不可用：仅生成上传目录（NAS 端 Container Manager 自行构建，或稍后重试导出 tar）'
}
