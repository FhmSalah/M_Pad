; Macro Pad — Windows installer (Inno Setup 6).
; Build with: desktop\build_installer.ps1  (it builds the app first, then runs ISCC).
;
; - Installs for all users into Program Files (admin prompt).
; - Each user's settings live in %APPDATA%\Macro Pad\config.json and are never touched.
; - Optional desktop shortcut and start-at-login (per user, set as the user who installs).

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "Macro Pad"
#define AppExe "Macro Pad.exe"
#define AppSource "..\..\release\Macro Pad"

[Setup]
; Never change AppId: Windows uses it to recognise upgrades of the same app.
AppId={{20ED813E-D1BB-4499-8D17-E5B2F811B67D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=FhmSalah
AppPublisherURL=https://github.com/FhmSalah/M_Pad
AppSupportURL=https://github.com/FhmSalah/M_Pad
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
UsedUserAreasWarning=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=MacroPad-Setup-{#AppVersion}
SetupIconFile=..\..\assets\app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; The app hides to the tray instead of closing, so we quit it ourselves (see [Code]).
CloseApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startatlogin"; Description: "&Start Macro Pad automatically when I sign in (runs in the tray)"; GroupDescription: "Startup:"

[InstallDelete]
; Remove files from an older version so nothing stale is left in the program folder.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Start-at-login is per user, so set it as the user who ran the installer (not as admin).
Filename: "{app}\{#AppExe}"; Parameters: "--enable-autostart"; Tasks: startatlogin; Flags: runasoriginaluser waituntilterminated
Filename: "{app}\{#AppExe}"; Parameters: "--disable-autostart"; Tasks: not startatlogin; Flags: runasoriginaluser waituntilterminated
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName} now"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{app}\{#AppExe}"; Parameters: "--quit"; RunOnceId: "QuitMacroPad"; Flags: waituntilterminated
Filename: "{app}\{#AppExe}"; Parameters: "--disable-autostart"; RunOnceId: "DisableAutostart"; Flags: waituntilterminated

[Code]
procedure CloseRunningApp();
var
  ResultCode: Integer;
  ExePath: String;
begin
  ExePath := ExpandConstant('{app}\{#AppExe}');
  // Ask a running copy to quit cleanly (it then releases the serial port).
  if FileExists(ExePath) then
    Exec(ExePath, '--quit', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  // Fallback for copies that didn't answer (e.g. older builds): end the process.
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "{#AppExe}"', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  CloseRunningApp();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "{#AppExe}"', '', SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
end;
