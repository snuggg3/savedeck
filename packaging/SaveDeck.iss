; Inno Setup script for SaveDeck.
; Build pipeline:  packaging\build.bat  (PyInstaller -> dist\SaveDeck\, then ISCC)
#define MyAppName "SaveDeck"
#define MyAppVersion "1.0.4"
#define MyAppExe "SaveDeck.exe"

[Setup]
AppId={{7A3C2F51-9B4E-4C8A-A1D2-53F0E1B9C7D4}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=snuggg3
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExe}
OutputDir=..\dist
OutputBaseFilename=SaveDeck-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\SaveDeck\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Launch {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent
