; Portable Mira installer — wraps dist\mira-portable into a single NSIS exe.
; The installed result is a writable folder with Mira.exe + runtime/ + data/,
; i.e. the same portable layout the desktop supervisor understands.
; Build with: makensis portable_installer.nsi  (run from scripts/)
;
; Result: dist\Mira Portable Setup.exe

Unicode true
!include "MUI2.nsh"

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
  ; runtime\ollama is excluded: its model blobs can reach >4 GB each, and the
  ; 32-bit makensis cannot mmap a single file over 4 GB. The portable folder
  ; keeps ollama for direct use; the one-click installer ships without it.
  File /r /x "ollama" "..\dist\mira-portable\*"
  CreateShortcut "$DESKTOP\Mira.lnk" "$INSTDIR\Mira.exe"
SectionEnd