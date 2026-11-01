#define MyAppName "SnowBotLauncher"
#define MyAppVersion "1.5.6"
#define MyAppExeName "SnowBotLauncher.exe"
#define MyAppId "{{3F6D2A9B-1C4E-4D7A-8B2F-5E9C7D1A6B30}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=SnowBot
DefaultDirName={autopf}\SnowBotLauncher
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=SnowBotLauncher-Setup-{#MyAppVersion}
SetupIconFile=..\app.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UsePreviousTasks=no
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Files]
Source: "..\dist\SnowBotLauncher\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\*"; DestDir: "{app}\docs"; Flags: recursesubdirs createallsubdirs
Source: "..\plugins\*"; DestDir: "{app}\plugins"; Excludes: "__pycache__,*.pyc"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\plugins"
