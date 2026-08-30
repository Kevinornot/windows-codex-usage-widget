Option Explicit
Dim fso, shell, folder, command, exitCode
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
command = Chr(34) & folder & "\run_widget.bat" & Chr(34)
exitCode = shell.Run(command, 0, True)
If exitCode <> 0 Then
    MsgBox "Codex Usage Widget could not start. Install Python 3.11 or newer, then confirm that python or py is available in PATH.", vbCritical, "Codex Usage Widget"
End If
