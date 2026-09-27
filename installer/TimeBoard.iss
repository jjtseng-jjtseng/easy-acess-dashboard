#ifndef AppVersion
  #error AppVersion must be provided by the release build.
#endif

[Setup]
AppId=TimeBoard.JJTseng
AppName=Time Board
AppVersion={#AppVersion}
AppVerName=Time Board {#AppVersion}
DefaultDirName={localappdata}\Programs\Time Board
DefaultGroupName=Time Board
UninstallDisplayIcon={app}\Time-Board.exe
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputDir=..\dist\installer
OutputBaseFilename=Time-Board-Setup

[Files]
Source: "..\dist\Time-Board\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Icons]
Name: "{group}\Time Board"; Filename: "{app}\Time-Board.exe"
Name: "{autodesktop}\Time Board"; Filename: "{app}\Time-Board.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Time-Board.exe"; Description: "Launch Time Board"; Flags: nowait postinstall skipifsilent
