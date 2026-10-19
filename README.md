# System Pulse

Небольшой оверлей для Windows, показывающий загрузку CPU и RAM, данные NVIDIA GPU и VRAM, скорость сетевого трафика и время работы системы. Оверлей следует за активным окном; положение можно менять через меню в системном трее.

## Требования

- Windows
- [Python Install Manager](https://www.python.org/downloads/) для Windows и последняя стабильная версия CPython 3
- Пакеты из `requirements.txt`
- NVIDIA GPU и установленный драйвер NVIDIA для показателей GPU и VRAM; без доступного NVML эти строки показывают `N/A`

## Запуск

```powershell
py install 3
py -V:PythonCore/3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe overlay.py
```

Для запуска без консольного окна используйте `start_overlay.vbs`. Для периодического восстановления процесса можно настроить Планировщик заданий на запуск `watchdog_overlay.vbs`.

Автозапуск при входе в Windows можно включить или выключить через меню значка в системном трее.

VBS-файлы используют `pythonw.exe` из локального окружения `.venv`, поэтому не зависят от буквы диска, текущей папки или порядка Python в `PATH`. `py install 3` устанавливает последний стабильный CPython 3, а `py -V:PythonCore/3` выбирает последний Python Core 3 для создания окружения. Перед первым запуском выполните команды установки выше.

## Локальные файлы

`settings.json` создаётся рядом с программой и хранит положение оверлея и его привязки к окнам на этом компьютере. `overlay.log` содержит диагностические сообщения. Эти файлы не входят в репозиторий.
