#define MyAppName "ポケヨヤ君"
#define MyAppVersion "1.25.0 RC5"
#define MyAppPublisher "PokeyoyaKun Project"
#define MyAppExeName "ポケヨヤ君.exe"

[Setup]
AppId={{9D8C7C17-78B0-4F43-9BC4-2C67DAF85D22}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PokeyoyaKun
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\release\installer
OutputBaseFilename=PokeyoyaKun_Setup_Ver1.25.0_RC5
SetupIconFile=..\assets\pokeyoya_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UsePreviousTasks=yes

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作成"; GroupDescription: "追加オプション:"; Flags: checkedonce
Name: "quicklaunchicon"; Description: "クイック起動にショートカットを作成"; GroupDescription: "追加オプション:"; Flags: unchecked

[Files]
Source: "..\release\dist\ポケヨヤ君.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\release\dist\ポケヨヤ君_設定.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\release\dist\ポケヨヤ君_Updater.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\release\dist\README.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\release\dist\pokeyoya_icon.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\ポケヨヤ君"; Filename: "{app}\ポケヨヤ君.exe"; WorkingDir: "{app}"
Name: "{group}\ポケヨヤ君 設定"; Filename: "{app}\ポケヨヤ君_設定.exe"; WorkingDir: "{app}"
Name: "{group}\アンインストール"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ポケヨヤ君"; Filename: "{app}\ポケヨヤ君.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\ポケヨヤ君"; Filename: "{app}\ポケヨヤ君.exe"; WorkingDir: "{app}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\ポケヨヤ君.exe"; Description: "ポケヨヤ君を起動"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\temp"
