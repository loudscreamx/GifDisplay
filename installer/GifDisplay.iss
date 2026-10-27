; Установщик GifDisplay. Сборка: сначала python -m PyInstaller GifDisplay.spec, затем ISCC installer\GifDisplay.iss
; Результат: installer\output\GifDisplay-Setup-<версия>.exe
#define AppName "GifDisplay"
#define AppVersion "1.0.0"
#define AppPublisher "loudscreamx"
#define AppURL "https://github.com/loudscreamx"
#define AppExe "GifDisplay.exe"

[Setup]
AppId={{AE680EAF-339A-4DF9-9DCF-8C1A454FEBE4}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
SetupIconFile=..\cat_gray.ico
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=output
OutputBaseFilename=GifDisplay-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
; программа ставится в Program Files и сама просит права администратора при запуске: датчикам и задаче автозапуска они нужны
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
ShowLanguageDialog=auto
VersionInfoVersion={#AppVersion}

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "uk"; MessagesFile: "compiler:Languages\Ukrainian.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "pl"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "pawnio"; Description: "{cm:InstallPawnIO}"; GroupDescription: "{cm:DriversGroup}"; Check: NeedPawnIO

[Files]
Source: "..\dist\GifDisplay\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; официальный установщик драйвера PawnIO (namazso): нужен библиотеке датчиков; скачивается installer\get_redist.ps1
Source: "redist\PawnIO_setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Tasks: pawnio

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\PawnIO_setup.exe"; Parameters: "-install -silent"; StatusMsg: "{cm:InstallingPawnIO}"; Flags: waituntilterminated; Tasks: pawnio
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN GifDisplay /F"; Flags: runhidden; RunOnceId: "DelTask"


[CustomMessages]
en.InstallPawnIO=Install the PawnIO driver (needed for CPU temperature, fans and pump)
en.DriversGroup=Drivers
en.InstallingPawnIO=Installing the PawnIO driver...
ru.InstallPawnIO=Установить драйвер PawnIO (нужен для температуры CPU, вентиляторов и помпы)
ru.DriversGroup=Драйверы
ru.InstallingPawnIO=Установка драйвера PawnIO...
uk.InstallPawnIO=Встановити драйвер PawnIO (потрібен для температури CPU, вентиляторів і помпи)
uk.DriversGroup=Драйвери
uk.InstallingPawnIO=Встановлення драйвера PawnIO...
de.InstallPawnIO=PawnIO-Treiber installieren (für CPU-Temperatur, Lüfter und Pumpe)
de.DriversGroup=Treiber
de.InstallingPawnIO=PawnIO-Treiber wird installiert...
fr.InstallPawnIO=Installer le pilote PawnIO (nécessaire pour la température du CPU, les ventilateurs et la pompe)
fr.DriversGroup=Pilotes
fr.InstallingPawnIO=Installation du pilote PawnIO...
es.InstallPawnIO=Instalar el controlador PawnIO (necesario para la temperatura de la CPU, ventiladores y bomba)
es.DriversGroup=Controladores
es.InstallingPawnIO=Instalando el controlador PawnIO...
it.InstallPawnIO=Installa il driver PawnIO (necessario per temperatura CPU, ventole e pompa)
it.DriversGroup=Driver
it.InstallingPawnIO=Installazione del driver PawnIO...
pt.InstallPawnIO=Instalar o driver PawnIO (necessário para temperatura da CPU, ventoinhas e bomba)
pt.DriversGroup=Drivers
pt.InstallingPawnIO=Instalando o driver PawnIO...
pl.InstallPawnIO=Zainstaluj sterownik PawnIO (potrzebny do temperatury CPU, wentylatorów i pompy)
pl.DriversGroup=Sterowniki
pl.InstallingPawnIO=Instalowanie sterownika PawnIO...
tr.InstallPawnIO=PawnIO sürücüsünü yükle (CPU sıcaklığı, fanlar ve pompa için gerekli)
tr.DriversGroup=Sürücüler
tr.InstallingPawnIO=PawnIO sürücüsü yükleniyor...
ja.InstallPawnIO=PawnIO ドライバーをインストール（CPU 温度・ファン・ポンプの取得に必要）
ja.DriversGroup=ドライバー
ja.InstallingPawnIO=PawnIO ドライバーをインストールしています...
ko.InstallPawnIO=PawnIO 드라이버 설치 (CPU 온도, 팬, 펌프에 필요)
ko.DriversGroup=드라이버
ko.InstallingPawnIO=PawnIO 드라이버를 설치하는 중...

[Code]
function NeedPawnIO: Boolean;
begin
  // уже стоит (ключ удаления PawnIO в любом из представлений реестра или его папка): галочку не предлагаем
  Result := not (RegKeyExists(HKLM64, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO')
    or RegKeyExists(HKLM32, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO')
    or DirExists(ExpandConstant('{commonpf64}\PawnIO')));
end;

procedure KillApp;
var
  rc: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, rc);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillApp;  // запущенная копия держит файлы: закрываем перед обновлением
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    KillApp;
end;
