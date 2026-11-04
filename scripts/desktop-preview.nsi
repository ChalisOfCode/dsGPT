Unicode True
!include "MUI2.nsh"
Name "dsGPT Development Client"
OutFile "..\dist\dsGPT-Desktop-Preview-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\dsGPT-Preview"
RequestExecutionLevel user
SetCompressor /SOLID lzma
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "This development client connects to an independently configured dsGPT backend. It requires Windows 11 and Microsoft Edge WebView2. The backend and model weights are installed separately. Isolated Work builds require a configured and verified runner on the PC. Your existing model and backend data will be preserved."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
Section "dsGPT desktop client"
 SetOutPath "$INSTDIR"
 File "..\dist\windows-client\dsGPT.exe"
 File /nonfatal "..\dist\windows-client\WebView2Loader.dll"
 File /nonfatal "..\dist\windows-client\libunwind.dll"
 File /oname=README.txt "..\clients\desktop\PREVIEW_README.txt"
 File /r "..\dist\windows-client\licenses"
 CreateDirectory "$SMPROGRAMS\dsGPT Preview"
 CreateShortcut "$SMPROGRAMS\dsGPT Preview\dsGPT.lnk" "$INSTDIR\dsGPT.exe"
 WriteUninstaller "$INSTDIR\Uninstall.exe"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\dsGPT-Preview" "DisplayName" "dsGPT Development Client"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\dsGPT-Preview" "DisplayVersion" "0.4.4"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\dsGPT-Preview" "UninstallString" '"$INSTDIR\Uninstall.exe"'
 WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\dsGPT-Preview" "NoModify" 1
 WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\dsGPT-Preview" "NoRepair" 1
SectionEnd
Section "Uninstall"
 Delete "$INSTDIR\dsGPT.exe"
 Delete "$INSTDIR\WebView2Loader.dll"
 Delete "$INSTDIR\libunwind.dll"
 Delete "$INSTDIR\README.txt"
 RMDir /r "$INSTDIR\licenses"
 Delete "$INSTDIR\Uninstall.exe"
 RMDir "$INSTDIR"
 Delete "$SMPROGRAMS\dsGPT Preview\dsGPT.lnk"
 RMDir "$SMPROGRAMS\dsGPT Preview"
 DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\dsGPT-Preview"
SectionEnd
