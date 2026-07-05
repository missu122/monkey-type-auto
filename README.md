# Text Typer

Локальное Windows-приложение для быстрой печати текста в активное окно.

## Запуск

Самый чистый запуск без терминала:

```text
run.vbs
```

Запасной вариант:

```text
run.bat
```

## Возможности

- печать текста из поля по заданному WPM;
- режим вставки целиком через буфер;
- повторение одного слова до `Stop` или `Esc`;
- Live OCR по выбранной области экрана;
- OCR из изображения в буфере или из файла;
- перенос после каждого слова или после каждых 10 слов;
- свой тег после каждого слова.

## Структура

```text
text_typer_tool/
  run.vbs
  run.bat
  README.md
  .gitignore
  src/
    text_typer.py
  assets/
    app_icon.ico
    app_icon.png
  tools/
    ocr_win.ps1
    install_tesseract.bat
  tessdata/
    eng.traineddata
    rus.traineddata
```

## Управление

1. Запусти `run.vbs`.
2. Вставь текст в большое поле.
3. Настрой `WPM` и нужные галочки.
4. Нажми `Start`.
5. Кликни в поле, куда надо печатать.
6. Нажми `F8`.

Остановка: `Stop` или `Esc`.

## OCR

OCR сначала пробует локальный Tesseract, потом встроенный Windows OCR.
Если OCR работает плохо, установи Tesseract через:

```text
tools/install_tesseract.bat
```

## GitHub

В репозиторий можно заливать всю эту папку. В `.gitignore` уже добавлены кеши Python, `.env`, логи и временные файлы.
