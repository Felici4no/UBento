; Inno Setup 6 — gera Output\UBento-Setup-<versão>.exe a partir de dist\UBento
#define AppName "UBento"
#define AppVersion "0.1.0"

[Setup]
AppId={{6E1B6C0E-6B0B-4F3B-9C1D-5B2E0A7F4D11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=UBento
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputBaseFilename=UBento-Setup-{#AppVersion}
SetupIconFile=..\assets\ubento.ico
UninstallDisplayIcon={app}\UBento.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\UBento\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\UBento.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\UBento.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\UBento.exe"; Description: "Abrir o UBento"; Flags: nowait postinstall skipifsilent
