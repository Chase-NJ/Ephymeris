; Included in the Electron installer by electron-builder (`nsis.include` in electron-builder.yml).
;
; ADR 0006's crossover: the Tauri shell installed Ephymeris to %LOCALAPPDATA%\Ephymeris, and this
; installer puts the Electron one in %LOCALAPPDATA%\Programs\Ephymeris. Left alone, a lab PC would
; keep both, and the old one still starts its own sidecar. So before installing, remove the Tauri
; copy if there is one.
;
; - Its silent uninstall leaves %APPDATA%\edu.hartlab.ephymeris (settings, database, wiring) alone:
;   the app-data checkbox is never ticked when no page is shown. Tried on Windows, 2026-11-15.
; - It runs in .onInit, before this installer makes its shortcuts: both are named Ephymeris, and the
;   Tauri uninstaller deletes its own by name.
; - When Tauri's updater launched this installer, the old app is still exiting; wait for its exe.
; - `_?=` runs the uninstaller in place, so ExecWait really waits; the folder is removed after, with
;   whatever older installs left in it. Only a folder that is plainly Tauri's: named Ephymeris and
;   holding Tauri's uninstall.exe (this installer's own is "Uninstall Ephymeris.exe").

!macro customInit
  Push $0
  Push $1
  Push $2
  Push $3

  ReadRegStr $1 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Ephymeris" "InstallLocation"
  StrCmp $1 "" tauri_done
  StrCpy $2 $1 1
  StrCmp $2 '"' 0 +2
    StrCpy $1 $1 -1 1
  StrCpy $2 $1 "" -10
  StrCmp $2 "\Ephymeris" 0 tauri_done
  IfFileExists "$1\uninstall.exe" 0 tauri_done

  ; Up to 15 s for the old app to let go of its exe.
  StrCpy $3 0
  IfFileExists "$1\ephymeris.exe" 0 tauri_unlocked
  tauri_wait:
    ClearErrors
    FileOpen $0 "$1\ephymeris.exe" a
    IfErrors tauri_locked
    FileClose $0
    Goto tauri_unlocked
  tauri_locked:
    IntOp $3 $3 + 1
    IntCmp $3 30 tauri_unlocked
    Sleep 500
    Goto tauri_wait
  tauri_unlocked:

  DetailPrint "Removing the Tauri copy of Ephymeris from $1"
  ExecWait '"$1\uninstall.exe" /S _?=$1' $0
  DetailPrint "Tauri uninstaller exited $0"
  RMDir /r "$1"

  tauri_done:
  Pop $3
  Pop $2
  Pop $1
  Pop $0
!macroend
