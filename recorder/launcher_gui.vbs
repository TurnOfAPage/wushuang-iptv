Option Explicit
' Wushuang IPTV Recorder - GUI entry (no console window).
' Trusted process chain: wscript (signed) -> installed Python (AV-trusted path).
' Falls back to bundled runtime when no installed Python found; if AV blocks
' protected folders the app auto-falls back to a writable dir with a notice.
' NOTE: keep this file pure ASCII (WSH parses ANSI; UTF-8 comments break lines).
Dim sh, fso, base, py, script, args, i, rc, k, v, p
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
py = ""
Dim vers, keys
vers = Array("3.14", "3.13", "3.12", "3.11", "3.10")
keys = Array("HKLM\SOFTWARE\Python\PythonCore\", "HKCU\SOFTWARE\Python\PythonCore\")
For Each v In vers
  For Each k In keys
    On Error Resume Next
    p = ""
    p = sh.RegRead(k & v & "\InstallPath\")
    On Error GoTo 0
    If p <> "" Then
      If fso.FileExists(p & "pythonw.exe") Then
        py = p & "pythonw.exe"
        Exit For
      End If
    End If
  Next
  If py <> "" Then Exit For
Next
If py = "" Then
  py = base & "python\pythonw.exe"
  sh.Environment("Process")("TCL_LIBRARY") = base & "python\tcl8.6"
  sh.Environment("Process")("TK_LIBRARY") = base & "python\tk8.6"
End If
script = base & "app\recorder\rec_main.py"
args = ""
For i = 0 To WScript.Arguments.Count - 1
  args = args & " """ & WScript.Arguments(i) & """"
Next
rc = sh.Run("""" & py & """ """ & script & """" & args, 0, True)
WScript.Quit rc
