Unicode True
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "FileFunc.nsh"
Name "dsGPT"
OutFile "..\dist\dsGPT-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\dsGPT-Managed"
RequestExecutionLevel user
SetCompressor /SOLID lzma
AutoCloseWindow true
ShowInstDetails show
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
Var NoSetup
Var ExistingInstall

Function .onInit
 ${IfNot} ${RunningX64}
   MessageBox MB_ICONSTOP "dsGPT requires 64-bit Windows."
   Abort
 ${EndIf}
 ${GetParameters} $0
 ClearErrors
 ${GetOptions} $0 "/NOSETUP" $1
 ${If} ${Errors}
   StrCpy $NoSetup "0"
 ${Else}
   StrCpy $NoSetup "1"
 ${EndIf}
FunctionEnd

Section "dsGPT"
 StrCpy $ExistingInstall "0"
 IfFileExists "$INSTDIR\application-manifest.json" 0 +2
 StrCpy $ExistingInstall "1"
 IfFileExists "$INSTDIR\python\pythonw.exe" 0 install
 ExecWait '"$INSTDIR\python\pythonw.exe" -I -m dsgpt.managed stop' $0
 ${If} $0 != 0
   MessageBox MB_ICONSTOP "The existing dsGPT backend could not stop safely. Saved data was preserved. Close dsGPT and retry."
   Abort
 ${EndIf}
 install:
 SetOutPath "$INSTDIR"
 File /r "..\dist\dsGPT-Application\*"
 CreateDirectory "$SMPROGRAMS\dsGPT"
 CreateShortcut "$DESKTOP\dsGPT.lnk" "$INSTDIR\python\pythonw.exe" '-B -I -m dsgpt_application launch' "$INSTDIR\client\dsGPT.exe"
 CreateShortcut "$SMPROGRAMS\dsGPT\dsGPT.lnk" "$INSTDIR\python\pythonw.exe" '-B -I -m dsgpt_application launch' "$INSTDIR\client\dsGPT.exe"
 CreateShortcut "$SMPROGRAMS\dsGPT\Repair dsGPT.lnk" "$INSTDIR\Repair dsGPT.cmd"
 CreateShortcut "$SMPROGRAMS\dsGPT\Connect Pixel.lnk" "$INSTDIR\Connect Pixel.cmd"
 CreateShortcut "$SMPROGRAMS\dsGPT\Startup Settings.lnk" "$INSTDIR\Startup Settings.cmd"
 CreateShortcut "$SMPROGRAMS\dsGPT\Recover Owner.lnk" "$INSTDIR\Recover Owner.cmd"
 CreateShortcut "$SMPROGRAMS\dsGPT\Stop Backend.lnk" "$INSTDIR\python\pythonw.exe" '-I -m dsgpt.managed stop'
 CreateShortcut "$SMPROGRAMS\dsGPT\Instructions.lnk" "$INSTDIR\START-HERE.txt"
 WriteUninstaller "$INSTDIR\Uninstall.exe"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\dsGPT-Managed" "DisplayName" "dsGPT"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\dsGPT-Managed" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\dsGPT-Managed" "DisplayVersion" "0.10.0"
 ${If} $NoSetup != "1"
  ${If} $ExistingInstall == "1"
   ; Launch reuses completed setup; an incomplete installation resumes setup itself.
   Exec '"$INSTDIR\python\pythonw.exe" -B -I -m dsgpt_application launch --connect-phone'
  ${Else}
   ExecWait '"$INSTDIR\python\python.exe" -B -I -m dsgpt_application setup' $0
   ${If} $0 == 3010
     MessageBox MB_ICONINFORMATION "Save your work and restart Windows. dsGPT setup will continue after you sign in."
   ${ElseIf} $0 != 0
     MessageBox MB_ICONINFORMATION "dsGPT is installed, but setup needs to resume. Open Start > dsGPT > Repair dsGPT. Your saved data is preserved."
   ${EndIf}
  ${EndIf}
 ${EndIf}
SectionEnd

Section "Uninstall"
 ExecWait '"$INSTDIR\python\pythonw.exe" -I -m dsgpt.managed startup-disable --confirm-startup-change' $0
 ${If} $0 != 0
   MessageBox MB_ICONSTOP "Could not remove dsGPT startup safely. Installation and data were preserved."
   Abort
 ${EndIf}
 ExecWait '"$INSTDIR\python\pythonw.exe" -I -m dsgpt.managed stop' $0
 ${If} $0 != 0
   MessageBox MB_ICONSTOP "The backend is still stopping. Retry after it finishes; data was preserved."
   Abort
 ${EndIf}
 ExecWait '"$INSTDIR\python\pythonw.exe" -I -m dsgpt_application remove-route' $0
 ${If} $0 != 0
   MessageBox MB_ICONSTOP "Could not verify the owned phone route. Installation was preserved; open Repair dsGPT and retry."
   Abort
 ${EndIf}
 RMDir /r "$INSTDIR\python"
 RMDir /r "$INSTDIR\client"
 RMDir /r "$INSTDIR\platform-tools"
 RMDir /r "$INSTDIR\android"
 Delete "$INSTDIR\Repair dsGPT.cmd"
 Delete "$INSTDIR\Connect Pixel.cmd"
 Delete "$INSTDIR\Recover Owner.cmd"
 Delete "$INSTDIR\Startup Settings.cmd"
 Delete "$INSTDIR\START-HERE.txt"
 Delete "$INSTDIR\application-manifest.json"
 Delete "$INSTDIR\Uninstall.exe"
 RMDir "$INSTDIR"
 Delete "$DESKTOP\dsGPT.lnk"
 RMDir /r "$SMPROGRAMS\dsGPT"
 DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\dsGPT-Managed"
 ; The separate data directory, models, credentials and shared dependencies are retained.
SectionEnd

