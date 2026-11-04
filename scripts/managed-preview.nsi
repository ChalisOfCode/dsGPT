Unicode True
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
Name "dsGPT Managed Development Preview"
OutFile "..\dist\dsGPT-Managed-Preview-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\dsGPT-Managed"
RequestExecutionLevel user
SetCompressor /SOLID lzma
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "Installs the dsGPT desktop preview and its local backend for Windows 11 x64. Requires Microsoft Edge WebView2. Optional CPU semantic retrieval also requires the Microsoft Visual C++ x64 runtime. Model setup is in Settings > Models; model downloads are separate. Isolated Work builds require a separately configured and tested Docker environment. This unsigned build has not passed Windows device acceptance. Close dsGPT windows before proceeding. Existing Ollama, Prometheus and saved data are preserved."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
 ${IfNot} ${RunningX64}
   MessageBox MB_ICONSTOP "This development build requires 64-bit Windows."
   Abort
 ${EndIf}
FunctionEnd

Section "dsGPT managed preview"
 IfFileExists "$INSTDIR\python\pythonw.exe" 0 install
 ExecWait '"$INSTDIR\python\pythonw.exe" -I -m dsgpt.managed stop' $0
 ${If} $0 != 0
   MessageBox MB_ICONSTOP "The existing backend could not stop safely. Installation was cancelled."
   Abort
 ${EndIf}
 install:
 SetOutPath "$INSTDIR"
 File /r "..\dist\windows-managed\*"
 CreateDirectory "$SMPROGRAMS\dsGPT Managed Preview"
 CreateShortcut "$SMPROGRAMS\dsGPT Managed Preview\dsGPT.lnk" "$INSTDIR\python\pythonw.exe" '-I -m dsgpt.managed launch' "$INSTDIR\client\dsGPT.exe"
 CreateShortcut "$SMPROGRAMS\dsGPT Managed Preview\Stop Backend.lnk" "$INSTDIR\python\pythonw.exe" '-I -m dsgpt.managed stop'
 CreateShortcut "$SMPROGRAMS\dsGPT Managed Preview\Backend Check.lnk" "$INSTDIR\Backend Check.cmd"
 CreateShortcut "$SMPROGRAMS\dsGPT Managed Preview\Startup Settings.lnk" "$INSTDIR\Startup Settings.cmd"
 CreateShortcut "$SMPROGRAMS\dsGPT Managed Preview\Recover Owner.lnk" "$INSTDIR\Recover Owner.cmd"
 CreateShortcut "$SMPROGRAMS\dsGPT Managed Preview\Setup Notes.lnk" "$INSTDIR\README.md"
 WriteUninstaller "$INSTDIR\Uninstall.exe"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\dsGPT-Managed" "DisplayName" "dsGPT Managed Development Preview"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\dsGPT-Managed" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\dsGPT-Managed" "DisplayVersion" "0.4.5-preview"
SectionEnd

Section "Uninstall"
 ExecWait '"$INSTDIR\python\pythonw.exe" -I -m dsgpt.managed startup-disable --confirm-startup-change' $0
 ${If} $0 != 0
   MessageBox MB_ICONSTOP "Startup task removal failed. Installation files are preserved. Review Startup Settings before retrying."
   Abort
 ${EndIf}
 ExecWait '"$INSTDIR\python\pythonw.exe" -I -m dsgpt.managed stop' $0
 ${If} $0 != 0
   MessageBox MB_ICONSTOP "Backend shutdown failed. Files and data are preserved. Retry after stopping the backend."
   Abort
 ${EndIf}
 RMDir /r "$INSTDIR\python"
 RMDir /r "$INSTDIR\client"
 Delete "$INSTDIR\Backend Check.cmd"
 Delete "$INSTDIR\Backend Console.cmd"
 Delete "$INSTDIR\History Import.cmd"
 Delete "$INSTDIR\Recover Owner.cmd"
 Delete "$INSTDIR\Startup Settings.cmd"
 Delete "$INSTDIR\README.md"
 Delete "$INSTDIR\provenance.json"
 Delete "$INSTDIR\payload-manifest.json"
 Delete "$INSTDIR\Uninstall.exe"
 RMDir "$INSTDIR"
 Delete "$SMPROGRAMS\dsGPT Managed Preview\dsGPT.lnk"
 Delete "$SMPROGRAMS\dsGPT Managed Preview\Stop Backend.lnk"
 Delete "$SMPROGRAMS\dsGPT Managed Preview\Recover Owner.lnk"
 Delete "$SMPROGRAMS\dsGPT Managed Preview\Startup Settings.lnk"
 Delete "$SMPROGRAMS\dsGPT Managed Preview\Backend Check.lnk"
 Delete "$SMPROGRAMS\dsGPT Managed Preview\Setup Notes.lnk"
 RMDir "$SMPROGRAMS\dsGPT Managed Preview"
 DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\dsGPT-Managed"
 ; Deliberately retain dsGPT data, model downloads, backups, credentials, and other runtimes.
SectionEnd
