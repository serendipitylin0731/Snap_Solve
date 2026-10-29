#define MyAppName "Snap Solve"
#define MyAppVersion "1.0.0"
#define MyAppExeName "SnapSolve.exe"

[Setup]
AppId={{E9A7FE7C-C4AC-4DC1-9EF5-83CE6299F3CB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Snap Solve
DefaultDirName={localappdata}\Programs\Snap Solve
DefaultGroupName=Snap Solve
PrivilegesRequired=lowest
OutputDir=release
OutputBaseFilename=SnapSolve-{#MyAppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\SnapSolve.exe
WizardStyle=modern
ArchitecturesAllowed=x64compatible

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "其他选项："; Flags: unchecked

[Files]
Source: "dist\SnapSolve\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: ".env.example"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Snap Solve"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Snap Solve"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 Snap Solve"; Flags: nowait postinstall skipifsilent

