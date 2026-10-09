; Inno Setup script of the Windows installer, build/windows/Smart-Meeting-Setup-<version>.exe, built by
; packaging/windows/build.sh (ISCC /DAppVersion=<version>). Installed for the user, without admin
; rights, in %LOCALAPPDATA%\Programs\Smart Meeting; the meetings stay in %LOCALAPPDATA%\smart-meeting.

; Paths from this folder (packaging\windows) to the project
#define Root "..\.."

[Setup]
; Never change it: Windows recognizes the installed app (updates, uninstall) by this id
AppId={{83B091EF-0128-4F74-B540-15B8939299CB}
AppName=Smart Meeting
AppVersion={#AppVersion}
AppVerName=Smart Meeting {#AppVersion}
AppPublisher=Kevin Graff
AppPublisherURL=https://github.com/graffkevin/smart-meeting
AppSupportURL=https://github.com/graffkevin/smart-meeting/issues
AppUpdatesURL=https://github.com/graffkevin/smart-meeting/releases
DefaultDirName={localappdata}\Programs\Smart Meeting
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#Root}\build\windows
OutputBaseFilename=Smart-Meeting-Setup-{#AppVersion}
SetupIconFile={#Root}\build\windows\app.ico
UninstallDisplayIcon={app}\Smart Meeting.exe
UninstallDisplayName=Smart Meeting
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; A new version over a running one: the app is closed first
CloseApplications=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; The libraries of the previous version: some are renamed from one version to the next
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#Root}\build\windows\dist\Smart Meeting\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Smart Meeting"; Filename: "{app}\Smart Meeting.exe"
Name: "{autodesktop}\Smart Meeting"; Filename: "{app}\Smart Meeting.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Smart Meeting.exe"; Description: "{cm:LaunchProgram,Smart Meeting}"; Flags: nowait postinstall skipifsilent
