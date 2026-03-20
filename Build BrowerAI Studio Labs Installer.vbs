Option Explicit

Dim fso, shell, scriptDir, workspaceRoot, pythonPath, buildScript, distPath, command, exitCode

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
workspaceRoot = fso.GetParentFolderName(fso.GetParentFolderName(scriptDir))
pythonPath = fso.BuildPath(workspaceRoot, "env\Scripts\python.exe")
buildScript = fso.BuildPath(scriptDir, "build_exe.py")
distPath = fso.BuildPath(scriptDir, "dist")

If Not fso.FileExists(pythonPath) Then
    MsgBox "Python environment not found at:" & vbCrLf & pythonPath, vbCritical, "BrowerAI Studio Labs Builder"
    WScript.Quit 1
End If

If Not fso.FileExists(buildScript) Then
    MsgBox "Build script not found at:" & vbCrLf & buildScript, vbCritical, "BrowerAI Studio Labs Builder"
    WScript.Quit 1
End If

command = """" & pythonPath & """ """ & buildScript & """"
exitCode = shell.Run(command, 0, True)

If exitCode = 0 Then
    shell.Run "explorer.exe """ & distPath & """", 1, False
    MsgBox "Build complete." & vbCrLf & "The setup executable is in:" & vbCrLf & distPath, vbInformation, "BrowerAI Studio Labs Builder"
Else
    MsgBox "The build did not complete successfully." & vbCrLf & "Exit code: " & exitCode, vbCritical, "BrowerAI Studio Labs Builder"
End If
