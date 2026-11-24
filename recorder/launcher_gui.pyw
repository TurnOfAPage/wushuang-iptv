# Wushuang IPTV Recorder - GUI entry for machines with installed Python.
# Double-click runs via the installed (AV-trusted) pythonw.exe association:
# no console window, no unsigned exe, no temp extraction.
# Keep this file pure ASCII.
import os
import sys

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(base, 'app', 'recorder'))
sys.path.insert(0, os.path.join(base, 'app', 'src'))
import rec_main

rec_main.main()
