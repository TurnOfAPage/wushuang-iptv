@echo off
rem ============================================================
rem 无双IPTV 鸿蒙精简版 · 命令行构建脚本
rem 产物: entry\build\default\outputs\default\entry-default-unsigned.hap
rem 注意: 产物未签名。签名/安装请用 DevEco Studio 打开本工程:
rem       登录华为账号 → File > Project Structure > Signing Configs
rem       勾选 Automatically generate signature → 运行到模拟器/真机
rem ============================================================
setlocal
set DEVECO=C:\Program Files\Huawei\DevEco Studio
if not exist "%DEVECO%\tools\hvigor\bin\hvigorw.bat" (
  echo 未找到 DevEco Studio，请修改本脚本中的 DEVECO 路径
  exit /b 1
)
set NODE_HOME=%DEVECO%\tools\node
set DEVECO_SDK_HOME=%DEVECO%\sdk
set PATH=%NODE_HOME%;%DEVECO%\jbr\bin;%PATH%
cd /d %~dp0
call "%DEVECO%\tools\hvigor\bin\hvigorw.bat" assembleHap --mode module -p product=default --no-daemon
endlocal
