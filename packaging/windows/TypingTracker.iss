#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef AppBrand
  #define AppBrand "TypingTracker"
#endif
#if AppBrand == "Sariana"
  #define DisplayName "Sariana · 伴你成长"
#else
  #define DisplayName "TypingTracker 打字管家"
#endif

[Setup]
AppId={{8A3CAB17-B864-4379-9BAA-A2C7AE85706D}
AppName={#DisplayName}
AppVersion={#AppVersion}
AppPublisher=JeropsWang
AppPublisherURL=https://github.com/JeropsWang/typing-tracker
DefaultDirName={localappdata}\Programs\{#AppBrand}
UsePreviousAppDir=yes
DefaultGroupName={#AppBrand}
UsePreviousGroup=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#AppBrand}-{#AppVersion}-windows-x64-setup
SetupIconFile={#PayloadDir}\app.ico
UninstallDisplayIcon={app}\{#AppBrand}.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter={#AppBrand}.exe,TypingTracker.exe
RestartApplications=no
LicenseFile={#PayloadDir}\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppBrand}"; Filename: "{app}\{#AppBrand}.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppBrand}"; Filename: "{app}\{#AppBrand}.exe"; WorkingDir: "{app}"; Tasks: desktopicon

#if AppBrand == "Sariana"
[InstallDelete]
; Only remove the previous product's executable and shortcuts during the rename.
Type: files; Name: "{app}\TypingTracker.exe"
Type: files; Name: "{group}\TypingTracker.lnk"
Type: files; Name: "{userprograms}\TypingTracker\TypingTracker.lnk"
Type: files; Name: "{autodesktop}\TypingTracker.lnk"
#endif

[Run]
Filename: "{app}\{#AppBrand}.exe"; Description: "{cm:LaunchProgram,{#AppBrand}}"; Flags: nowait postinstall skipifsilent unchecked

; No UninstallDelete: user records in %APPDATA%\TypingTracker are preserved.
