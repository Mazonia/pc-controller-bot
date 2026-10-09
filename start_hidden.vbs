' PC Remote Sentinel — Silent Background Commander Launcher
' Launches the bot directly in the background with zero terminal window or taskbar flicker.
Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
strCurDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strCurDir

If FSO.FileExists(strCurDir & "\pc-sentinel.exe") Then
    WshShell.Run """" & strCurDir & "\pc-sentinel.exe"" """ & strCurDir & "\bot.py""", 0, False
Else
    WshShell.Run "python """ & strCurDir & "\bot.py""", 0, False
End If
