' Start the app and open it in the browser.
' Uses "python -m streamlit" (works even when the streamlit.exe script folder is
' not on PATH) and a visible "cmd /k" window so any error stays readable; close
' the window to stop the app. Do not add --server.headless true: it stops
' Streamlit from opening the browser, so a hidden launch then shows nothing.
Dim strDir
strDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run _
    "cmd /k cd /d """ & strDir & """ && python -m streamlit run app.py", 1, False
