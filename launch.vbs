Dim strDir
strDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run "cmd /c cd /d """ & strDir & """ && streamlit run app.py --server.headless true", 0, False
