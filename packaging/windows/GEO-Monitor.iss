#ifndef PayloadDir
  #define PayloadDir "..\..\build\windows\payload"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist\windows"
#endif
#ifndef ReleaseVersion
#define ReleaseVersion "1.0.19"
#endif

[Setup]
AppId={{FA150F57-5B97-4191-B1CB-7997E9734151}
AppName=GEO 监测中心
AppVersion={#ReleaseVersion}
AppPublisher=GEO Monitor
DefaultDirName={localappdata}\Programs\GEO-Monitor
DefaultGroupName=GEO 监测中心
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=GEO-Monitor-Setup-{#ReleaseVersion}
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\GEO-Monitor.exe
SetupIconFile=..\..\assets\geo-logo.ico
SetupLogging=yes
CloseApplications=no
RestartApplications=no
LicenseFile=..\..\LICENSE
InfoAfterFile=InstallNotes.txt
CreateUninstallRegKey=not IsVerificationInstall

[Languages]
; The offline compiler bundle used for releases does not include the optional
; Chinese language file. The installed application itself remains Chinese.
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: checkedonce

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\GEO 监测中心"; Filename: "{app}\GEO-Monitor.exe"; WorkingDir: "{app}"; Check: not IsVerificationInstall
Name: "{autodesktop}\GEO 监测中心"; Filename: "{app}\GEO-Monitor.exe"; WorkingDir: "{app}"; Tasks: desktopicon; Check: not IsVerificationInstall
Name: "{group}\卸载 GEO 监测中心"; Filename: "{uninstallexe}"; Check: not IsVerificationInstall

[Run]
Filename: "{app}\GEO-Monitor.exe"; Description: "打开 GEO 监测中心"; Flags: nowait postinstall skipifsilent

; User data lives outside {app}. Updating or uninstalling retains drafts,
; saved platform sessions, and report history.

[Code]
function IsVerificationInstall: Boolean;
begin
  { The release check installs into an isolated folder without registering over
    an existing user's installation or replacing their shortcuts. }
  Result := ExpandConstant('{param:VerifyInstall|0}') = '1';
end;
