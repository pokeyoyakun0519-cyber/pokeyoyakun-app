#define MyAppName "ポケヨヤ君 Owner Edition"
#define MyAppVersion "1.25.0 RC3 Owner"
#define MyAppPublisher "PokeyoyaKun Project"
#define MyAppExeName "PokeyoyaKun_OwnerEdition.exe"

[Setup]
AppId={{EEE1247B-F511-498F-94A9-327CCF785AA1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\PokeyoyaKunOwner
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\release\owner_installer_rc3
OutputBaseFilename=PokeyoyaKun_Owner_Setup_Ver1.25.0_RC3
SetupIconFile=..\assets\pokeyoya_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Files]
Source: "..\release\owner_dist_rc3\PokeyoyaKun_OwnerEdition.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\release\owner_dist_rc3\PokeyoyaKun_Owner_Settings.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\release\owner_dist_rc3\PokeyoyaKunOwnerUpdater.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\release\owner_dist_rc3\release-integrity.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\release\owner_dist_rc3\OWNER_EDITION_README.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\release\owner_dist_rc3\pokeyoya_icon.png"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\ポケヨヤ君 Owner Edition"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\ポケヨヤ君 Owner 設定"; Filename: "{app}\PokeyoyaKun_Owner_Settings.exe"; WorkingDir: "{app}"
Name: "{group}\アンインストール"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Owner Editionを起動"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\temp"
