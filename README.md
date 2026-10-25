# Softpalaroid

Десктопное приложение (Windows), которое превращает обычные фотографии в
**полароидные снимки** и раскладывает их на **листе 10×15 см** — готовом к
печати как обычное фото (300 DPI).

![Интерфейс Softpalaroid](docs/screenshot.png)

Пример готового листа (1772×1181 px, 300 DPI):

![Готовый лист 10x15](docs/sample_10x15.jpg)

## Возможности

- 📐 Лист 10×15 см: альбомная (15×10) или книжная (10×15) ориентация
- 🖼️ Раскладка: **1, 2 или 4** полароида на листе (в каждое — своё фото)
- 🖱️ Редактирование **прямо в окне предпросмотра**:
  - масштаб фото внутри рамки — колесом мыши
  - наклон карточки — ручкой сверху, `Shift`+колесо или `Alt`+перетаскивание
  - сдвиг фото в рамке — перетаскиванием (или стрелками клавиатуры)
  - перемещение карточки по листу — перетаскиванием за белую рамку
  - масштаб просмотра листа — `Ctrl`+колесо
- ✍️ Подпись на белой рамке (рукописным шрифтом, если доступен)
- 🎞️ Фильтры в стиле плёнки: винтаж, тёплый, холодный, выцветшая плёнка,
  сепия, ч/б (виньетка + зерно)
- 💾 Экспорт в **JPG/PNG с 300 DPI** — печатается как стандартное фото 10×15
- 🖨️ Печать 10×15 прямо из приложения
- 📂 Drag-and-drop: фото можно перетащить файлом в окно программы

| Действие | Как |
|---|---|
| Масштаб фото | колесо мыши над карточкой |
| Наклон | `Shift`+колесо, ручка ⤾ сверху, `Alt`+тянуть |
| Сдвиг фото | тянуть фото мышью / стрелки |
| Двигать карточку | тянуть за белую рамку |
| Масштаб просмотра | `Ctrl`+колесо, тянуть пустое место |
| Загрузить фото | двойной клик по карточке |

Все параметры также дублируются слайдерами на панели справа.

## Скачать установщик (Windows)

Готовый установщик собирается автоматически на GitHub Actions:

- стабильные версии — в разделе
  [Releases](https://github.com/gjjut/Softpalaroid/releases)
  (`Softpalaroid-Setup-<версия>.exe`);
- промежуточные сборки — **Actions → Build Windows installer →** выбрать
  запуск **→ Artifacts: Softpalaroid-Windows**.

## Запуск из исходников

Требуется Python 3.11+.

```bash
git clone https://github.com/gjjut/Softpalaroid.git
cd Softpalaroid
python -m venv .venv
.venv\Scripts\activate      # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
python run.py               # можно передать фото: python run.py photo.jpg
```

## Сборка .exe и установщика

На Windows одной командой (для установщика нужен
[Inno Setup 6](https://jrsoftware.org/isdl.php)):

```bat
packaging\build.bat
```

Результат: `dist\Softpalaroid\Softpalaroid.exe` (программа без установки) и
`dist\installer\Softpalaroid-Setup-<версия>.exe` (установщик).

Вручную:

```bash
pip install -r requirements.txt pyinstaller
pyinstaller packaging/Softpalaroid.spec --noconfirm
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

### Публикация релиза

1. Поднять версию в `src/softpalaroid/__init__.py` и `MyAppVersion` в
   `packaging/installer.iss`.
2. `git tag v0.2.0 && git push origin v0.2.0` — GitHub Actions соберёт
   установщик и прикрепит его к новому Release.

## Структура проекта

```
run.py                      — запуск из исходников
src/softpalaroid/
    model.py                — геометрия листа и полароида, раскладки 1/2/4
    filters.py              — плёночные фильтры (Pillow)
    render.py               — рендер листа в 300 DPI для экспорта/печати
    canvas.py               — интерактивный предпросмотр (мышь, наклон, масштаб)
    main_window.py          — главное окно и панель настроек
    app.py                  — точка входа
packaging/
    Softpalaroid.spec       — PyInstaller (Softpalaroid.exe)
    installer.iss           — Inno Setup (установщик)
    build.bat               — сборка в одну команду
tools/                      — генерация иконки, GUI smoke-тест для CI
tests/                      — unit-тесты ядра
.github/workflows/          — автосборка установщика на Windows
```

## Тесты

```bash
python -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen python tools/smoke_gui.py   # GUI-прогон
```

## Стек

Python 3.11+ · [PySide6 (Qt)](https://doc.qt.io/qtforpython-6/) ·
[Pillow](https://pillow.readthedocs.io/) ·
[PyInstaller](https://pyinstaller.org/) · [Inno Setup](https://jrsoftware.org/isinfo.php)

## Планы

- произвольное количество карточек и свободное добавление/удаление;
- цвет фона листа и рамки;
- сохранение/открытие проектов;
- поворот самого фото и отражение.
