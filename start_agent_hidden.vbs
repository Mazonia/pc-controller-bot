' PC Remote Sentinel - Silent Background Agent Launcher
' Runs start_agent.bat completely hidden in background without any visible terminal window.
Set WshShell = CreateObject("WScript.Shell")
strCurDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strCurDir
WshShell.Run "cmd.exe /c start_agent.bat", 0, False
