#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif

[Setup]
AppId={{8A3CAB17-B864-4379-9BAA-A2C7AE85706D}
AppName=TypingTracker 打字管家
AppVersion={#AppVersion}
AppPublisher=JeropsWang
AppPublisherURL=https://github.com/JeropsWang/typing-tracker
DefaultDirName={localappdata}\Programs\TypingTracker
DefaultGroupName=TypingTracker
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=TypingTracker-{#AppVersion}-windows-x64-setup
SetupIconFile={#PayloadDir}\app.ico
UninstallDisplayIcon={app}\TypingTracker.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
LicenseFile={#PayloadDir}\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\TypingTracker"; Filename: "{app}\TypingTracker.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\TypingTracker"; Filename: "{app}\TypingTracker.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\TypingTracker.exe"; Description: "{cm:LaunchProgram,TypingTracker}"; Flags: nowait postinstall skipifsilent unchecked

; No UninstallDelete: user records in %APPDATA%\TypingTracker are preserved.
