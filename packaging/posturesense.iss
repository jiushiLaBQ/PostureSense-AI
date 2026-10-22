; ============================================================
;  智姿 AI (PostureSense AI) — Inno Setup 安装脚本
;
;  用法: 先执行 python packaging\build.py 产出 dist\PostureSenseAI，
;        再用 Inno Setup 6.3+ 编译本脚本（x64compatible 指令需 6.3+）:
;        iscc packaging\posturesense.iss
;
;  ✅ 状态: 已实测（2026-10-19, Inno Setup 6.7.3）——
;    编译成功产出 dist\installer\PostureSenseAI-Setup-0.1.0.exe（180MB）；
;    静默安装 → 安装后 exe 冒烟通过 → 静默卸载，用户数据目录 %USERPROFILE%\PostureSenseAI 卸载后保留。
;
;  数据策略: 用户数据在 %USERPROFILE%\PostureSenseAI\（数据库与导出），
;            卸载【不自动删除】——由用户自行决定是否保留（见 USER_MANUAL §10）。
; ============================================================

#define AppName "智姿 AI (PostureSense AI)"
#define AppExeName "PostureSenseAI.exe"
#define AppVersion "0.1.0"
#define AppPublisher "PostureSense AI Project"

[Setup]
AppId={{7E3C9A21-5F4B-4C2D-9E8A-1B2C3D4E5F60}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\PostureSenseAI
DefaultGroupName=PostureSense AI
; 输出
OutputDir=..\dist\installer
OutputBaseFilename=PostureSenseAI-Setup-{#AppVersion}
; 压缩
Compression=lzma2/ultra64
SolidCompression=yes
; 仅 64 位（mediapipe/Qt6 需要）
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 界面
WizardStyle=modern
; 无管理员也可安装（onedir 复制）
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; 安装前确认许可义务已就绪（NOTICE 随包）
LicenseFile=..\NOTICE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; 简体中文语言包为 Inno 官方附带，若环境缺失可删此行
; Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
; onedir 全部内容（Qt dll 独立文件，满足 LGPL 可替换要求）
Source: "..\dist\PostureSenseAI\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; 署名与许可信息
Source: "..\NOTICE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked

[Run]
; 安装后可立即启动
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 仅删除安装目录内的缓存；用户数据目录 %USERPROFILE%\PostureSenseAI 不动
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
