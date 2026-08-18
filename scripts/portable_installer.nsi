; Portable Mira installer — wraps dist\mira-portable into a single NSIS exe.
; The installed result is a writable folder with Mira.exe + runtime/ + data/,
; i.e. the same portable layout the desktop supervisor understands.
; Build with: makensis portable_installer.nsi  (run from scripts/)
;
; Result: dist\Mira Portable Setup.exe

Unicode true
!include "MUI2.nsh"

Name "Mira Portable"
OutFile "..\dist\Mira Portable Setup.exe"
InstallDir "$LOCALAPPDATA\Mira Portable"
RequestExecutionLevel user

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "English"

Section "Mira"
  SetOutPath "$INSTDIR"
  File /r "..\dist\mira-portable\*"
  CreateShortcut "$DESKTOP\Mira.lnk" "$INSTDIR\Mira.exe"
  CreateDirectory "$LOCALAPPDATA\Mira Portable"
SectionEnd