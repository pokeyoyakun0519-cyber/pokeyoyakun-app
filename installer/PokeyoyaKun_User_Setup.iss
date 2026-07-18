#define MyAppName "ポケヨヤ君"
#define MyAppVersion "1.25.0 RC5 User Edition"
#define MyAppPublisher "PokeyoyaKun Project"
#define MyAppExeName "ポケヨヤ君.exe"

[Setup]
AppId={{6B791901-293B-4D40-A6D1-F1A5AD1A6BB3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\PokeyoyaKun
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\release\user_installer_rc5
OutputBaseFilename=PokeyoyaKun_User_Setup_Ver1.25.0_RC5
SetupIconFile=..\assets\pokeyoya_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作成"; GroupDescription: "追加オプション:"; Flags: checkedonce

[Files]
Source: "..\release\user_dist_rc5\ポケヨヤ君.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\release\user_dist_rc5\ポケヨヤ君_設定.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\release\user_dist_rc5\PokeyoyaKunUpdater.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\release\user_dist_rc5\release-integrity.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\release\user_dist_rc5\README.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\release\user_dist_rc5\使用方法.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\release\user_dist_rc5\pokeyoya_icon.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\ポケヨヤ君"; Filename: "{app}\ポケヨヤ君.exe"; WorkingDir: "{app}"
Name: "{group}\ポケヨヤ君 設定"; Filename: "{app}\ポケヨヤ君_設定.exe"; WorkingDir: "{app}"
Name: "{group}\アンインストール"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ポケヨヤ君"; Filename: "{app}\ポケヨヤ君.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\ポケヨヤ君.exe"; Description: "ポケヨヤ君を起動"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\temp"
