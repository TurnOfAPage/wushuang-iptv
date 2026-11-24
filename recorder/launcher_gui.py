# -*- coding: utf-8 -*-
"""GUI 启动器：优先用系统已安装 Python（杀软信任的安装路径身份）运行 app/recorder/rec_main.py；
无安装 Python 时回退 bundled 签名运行时。自身不解包、不写保护目录。"""
import os
import subprocess
import sys

GUI = True


def find_python(base):
    exe_name = 'pythonw.exe' if GUI else 'python.exe'
    try:
        import winreg
        vers = []
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for wow in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    k = winreg.OpenKey(hive, r'SOFTWARE\Python\PythonCore', 0,
                                       winreg.KEY_READ | wow)
                except OSError:
                    continue
                i = 0
                while True:
                    try:
                        vers.append(winreg.EnumKey(k, i))
                        i += 1
                    except OSError:
                        break
        def vkey(v):
            try:
                return tuple(int(x) for x in v.split('.')[:2])
            except ValueError:
                return (0, 0)
        for v in sorted(set(vers), key=vkey, reverse=True):
            if vkey(v) < (3, 10):
                continue
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for wow in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                    try:
                        k = winreg.OpenKey(hive, r'SOFTWARE\Python\PythonCore\%s\InstallPath' % v,
                                           0, winreg.KEY_READ | wow)
                        path = winreg.QueryValue(k, None)
                        exe = os.path.join(path, exe_name)
                        if os.path.exists(exe):
                            return exe
                    except OSError:
                        continue
    except Exception:
        pass
    return os.path.join(base, 'python', exe_name)


base = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) \
    else os.path.dirname(os.path.abspath(__file__))
py = find_python(base)
script = os.path.join(base, 'app', 'recorder', 'rec_main.py')
env = dict(os.environ)
if os.path.basename(os.path.dirname(py)) == 'python':
    env['TCL_LIBRARY'] = os.path.join(base, 'python', 'tcl8.6')
    env['TK_LIBRARY'] = os.path.join(base, 'python', 'tk8.6')
p = subprocess.Popen([py, script] + sys.argv[1:], env=env, cwd=base)
sys.exit(p.wait())
