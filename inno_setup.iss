; DigitalBeing.iss — Inno Setup скрипт для Digital Being
; Создаёт setup.exe — Windows-установщик с визардом «Далее → Установить»
;
; Использование:
;   1. Собрать .exe через `python build.py`
;   2. Установить Inno Setup: https://jrsoftware.org/isinfo.php
;   3. Скомпилировать: ISCC.exe inno_setup.iss
;   ИЛИ: python build_installer.py (автоматически вызовет ISCC.exe)
;
; Результат:
;   installer_output/DigitalBeing_Setup_v0.1.3.exe (~50 MB)

#define MyAppName "Digital Being"
#define MyAppVersion "0.1.3"
#define MyAppPublisher "Digital Being Team"
#define MyAppURL "https://github.com/han13ter2014-web/Digital_being"
#define MyAppExeName "DigitalBeing.exe"

[Setup]
; Идентификатор приложения (НЕ МЕНЯТЬ после релиза — используется для обновлений)
AppId={{8B6F2D9E-7A3C-4F5B-9E8D-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Куда ставить (по умолчанию Program Files)
DefaultDirName={autopf}\{#MyAppName}
; Имя папки в меню Пуск
DefaultGroupName={#MyAppName}
; Лицензия
LicenseFile=installer\license.txt
; Текст "Перед установкой" (InfoBeforeFile показывается до лицензии)
InfoBeforeFile=installer\welcome.txt

; Куда положить готовый setup.exe
OutputDir=installer_output
OutputBaseFilename=DigitalBeing_Setup_v{#MyAppVersion}

; Иконка установщика (если есть)
SetupIconFile=assets\icon.ico

; Сжатие: lzma — максимальное
Compression=lzma2/ultra64
SolidCompression=yes

; Красивый современный стиль
WizardStyle=modern
WizardSizePercent=110

; Права администратора (для Program Files и создания ярлыков)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Минимальная версия Windows 10 (поддержка широкой аудитории)
MinVersion=10.0

; Сжатые данные (быстрее извлечение, меньше места)
LZMAUseSeparateProcess=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Ярлыки и автозапуск — пользователь выбирает при установке
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные значки:"
Name: "startmenu"; Description: "Создать ярлык в меню Пуск"; GroupDescription: "Дополнительные значки:"
Name: "autostart"; Description: "Запускать Digital Being при входе в Windows"; GroupDescription: "Дополнительные значки:"

[Files]
; Главный exe (PyInstaller-сборка)
Source: "dist\DigitalBeing.exe"; DestDir: "{app}"; Flags: ignoreversion

; README (открывается после установки)
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion; Check: FileExists('LICENSE')

; Документация (опционально)
Source: "docs\USAGE.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "docs\BUILD.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "docs\WILL.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "docs\ARCHITECTURE.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
; Ярлык в меню Пуск → Запускает агента
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: startmenu

; Ярлык "Удалить" в меню Пуск
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

; Ярлык на рабочем столе
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Автозапуск (HKCU\...\Run — для текущего пользователя, без админ-прав)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "DigitalBeing"; \
    ValueData: """{app}\{#MyAppExeName}"" --autostart"; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
; После установки — спросить, запустить ли агента сразу
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,Digital Being}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Чистим пользовательские данные при деинсталляции (опционально — обычно НЕ удаляем, чтобы пользователь не потерял чекпоинты)
; Type: filesandordirs; Name: "{app}\data\logs"
; Type: filesandordirs; Name: "{app}\data\checkpoints"
; Type: filesandordirs; Name: "{app}\data\memory"

[Messages]
; Кастомизация текстов (если есть ru-файлы)