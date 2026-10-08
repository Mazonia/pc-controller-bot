' PC Remote Sentinel - Silent Background Launcher
' Runs run.bat completely hidden in background without keeping terminal window open.
Set WshShell = CreateObject("WScript.Shell")
strCurDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strCurDir
WshShell.Run "cmd.exe /c run.bat", 0, False
