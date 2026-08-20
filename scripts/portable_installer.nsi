; Portable Mira installer — wraps dist\mira-portable into a single NSIS exe.
; The installed result is a writable folder with Mira.exe + runtime/ + data/,
; i.e. the same portable layout the desktop supervisor understands.
; Build with: makensis portable_installer.nsi  (run from scripts/)
;
; Result: dist\Mira Portable Setup.exe
;
; On install the setup also registers Mira's two host scheduled tasks (Mira
; Telemetry every 1 min, Mira Sense every 5 min) by running scripts\install_tasks.ps1,
; so the HUD metrics and the mind-loop observations work immediately on a fresh
; machine with no manual step. The uninstaller removes those tasks again.

Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"

; Use the Mira orb+M monogram for the installer and uninstaller icons.
!define MUI_ICON "..\desktop\assets\icon.ico"
!define MUI_UNICON "..\desktop\assets\icon.ico"

Name "Mira Portable"
OutFile "..\dist\Mira Portable Setup.exe"
InstallDir "$LOCALAPPDATA\Mira Portable"
RequestExecutionLevel user

; Solid LZMA: best ratio for a ~1.3GB bundle (site-packages + onnx models
; compress well). Slower to build, smaller to ship.
SetCompressor /SOLID lzma

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "English"

Section "Mira"
  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ; runtime\ollama is excluded: its model blobs can reach >4 GB each, and the
  ; 32-bit makensis cannot mmap a single file over 4 GB. The portable folder
  ; keeps ollama for direct use; the one-click installer ships without it.
  File /r /x "ollama" "..\dist\mira-portable\*"
  CreateShortcut "$DESKTOP\Mira.lnk" "$INSTDIR\Mira.exe"

  ; Bundle the host sampler scripts + task installers so the installed copy
  ; registers scheduled tasks pointing at itself (self-locating wrappers).
  SetOutPath "$INSTDIR\scripts"
  File "mira_sense.ps1"
  File "mira_telemetry.ps1"
  File "run_sense.ps1"
  File "run_telemetry.ps1"
  File "install_tasks.ps1"

  ; Register the scheduled tasks for this user. Runs in the background window
  ; the installer already has; failures are non-fatal (a re-run of the script
  ; or the installer repairs it later).
  nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scripts\install_tasks.ps1"'
  Pop $0
SectionEnd

Section "Uninstall"
  ; Remove Mira's host scheduled tasks along with the app.
  nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scripts\install_tasks.ps1" -Uninstall'
  Pop $0

  Delete "$DESKTOP\Mira.lnk"
  RMDir /r "$INSTDIR"
SectionEnd