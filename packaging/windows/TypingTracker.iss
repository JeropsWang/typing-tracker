; Windows 发布安装配置，由 build_release.py 显式传入版本、负载和输出目录。
; 使用稳定 AppId 与旧数据路径，支持产品更名升级；不会把用户统计加入卸载清理。
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
; AppId 必须稳定，升级才会识别原安装位置与卸载记录。
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
; 仅安装已核验的发布负载，用户数据库由运行时放在独立旧数据目录。
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppBrand}"; Filename: "{app}\{#AppBrand}.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppBrand}"; Filename: "{app}\{#AppBrand}.exe"; WorkingDir: "{app}"; Tasks: desktopicon

#if AppBrand == "Sariana"
[InstallDelete]
; 更名升级只移除旧可执行文件和快捷方式，不清理用户数据或整个安装目录。
Type: files; Name: "{app}\TypingTracker.exe"
Type: files; Name: "{group}\TypingTracker.lnk"
Type: files; Name: "{userprograms}\TypingTracker\TypingTracker.lnk"
Type: files; Name: "{autodesktop}\TypingTracker.lnk"
#endif

[Run]
Filename: "{app}\{#AppBrand}.exe"; Description: "{cm:LaunchProgram,{#AppBrand}}"; Flags: nowait postinstall skipifsilent unchecked

; 不定义 UninstallDelete：保留 %APPDATA%\TypingTracker 中的用户记录。
