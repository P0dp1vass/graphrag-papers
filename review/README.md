# Подготовка к ревью GraphRAG

Срез проекта: **25 ноября 2026 года**. Материалы на русском; поиск и ответы приложения остаются английскими. UI не добавлялся.

**Дополнение после аудита:** по отдельному запросу обработаны все 28 Python-файлов: форматирование и редактура комментариев изменили 25 файлов. AST и строковые значения сохранены, 36 тестов проходят. [Отчёт обработки](checks/code_cleanup/README.md). Диапазоны строк в исходном разборе относятся к версии до форматирования; [карта строк](checks/code_cleanup/line_map.json) связывает их с текущей. Установка и ограничения внешнего skill — в [INSTALLATION.json](../.agents/skills/remove-ai-marks/INSTALLATION.json).

**Финальная ручная правка:** после обработки автор вручную отредактировал `scripts/*.py` (убраны docstrings и комментарии, поправлено форматирование); `src/` и `tests/` сохранены рабочими. Перед публикацией пароль Neo4j вынесен в `NEO4J_PASSWORD`, обновлены README, `.gitignore` и верификатор. Актуальные хеши — [final_state.json](checks/final_state.json). Цитаты и номера строк в разборе и карточках описывают аудированный срез, а не текущие файлы скриптов.

## Что читать и в каком порядке

1. [Полный разбор проекта](PROJECT_REVIEW_RU.md) — задача, архитектура, результаты, достоинства, проблемы и приоритеты.
2. [Разбор кода](CODE_WALKTHROUGH_RU.md) — все 19 рабочих Python-файлов, 2 файла `src/`, 3 файла тестов и настройки; объяснения Python, HTTP, Cypher, retrieval.
3. [Презентация и ответы ревьюеру](REVIEW_PRESENTATION_RU.md) — речь на 7–10 минут, безопасное демо, неудобные вопросы и план подготовки.
4. [Анки](anki/README.md) — готовая колода, текстовый импорт, исходные карточки, теги и порядок изучения.
5. [Проверки](checks/) — машинные свидетельства, а не только выводы ассистента.

**Если есть только час:** прочитай разделы 1–4 и 7 полного разбора, отрепетируй короткую речь и изучи карточки с тегом `priority::core`.

## Что было сделано в первичном аудите

- Прочитана рабочая логика, тесты и конфигурация. Проверен синтаксис 24 исходных Python-файлов, повторно прошли 36 unit-тестов.
- Проверены текущие данные, состояние Neo4j, бюджет embedding-токенов и контракт API с моками.
- Отдельными примерами воспроизведены проблемы структурной валидации; повторно посчитана confusion matrix сохранённого Laya-eval.
- По SHA-256 проверена неизменность 29 рабочих исходных/config/lock файлов.
- Первичный проход внешним skill был read-only: установлен локально в `.agents/skills/remove-ai-marks/`, autoinvoke выключен; по `scripts/`, `src/`, `tests/` — **0 находок**, без пропусков файлов, без переписывания кода и hooks. Позже, по отдельному запросу, тем же skill обработан весь Python-код — scope и ограничения в [skill_application.json](checks/code_cleanup/skill_application.json).
- Созданы только материалы в `review/` и локальная установка skill. Функциональные улучшения ниже — **план**, а не скрыто выполненные исправления.

Нулевая Unicode-находка не доказывает человеческое авторство, отсутствие статистических меток или качество программы. Помощь ИИ в разработке, разметке и этом разборе не скрывается.

## Где смотреть доказательства

| Утверждение | Файл |
|---|---|
| Список и хеши исходников | [source_manifest.json](checks/source_manifest.json) |
| Исходники не менялись во время основного аудита | [source_integrity.json](checks/source_integrity.json) |
| Синтаксис и определения | [syntax_and_definitions.json](checks/syntax_and_definitions.json) |
| 36 успешных unit-тестов | [unit_tests.json](checks/unit_tests.json) |
| Размер и инварианты графа | [graph.json](checks/graph.json) |
| Состояние входных данных | [input_data.json](checks/input_data.json) |
| Контракт и startup API с моками | [api_contract.json](checks/api_contract.json) |
| Обрезание входов embedding-модели | [embedding_budget.json](checks/embedding_budget.json) |
| Примеры слабой валидации и версии | [extra_evidence.json](checks/extra_evidence.json) |
| Первичный внешний Unicode-аудит | [watermark_audit.json](checks/watermark_audit.json) |
| Последующая обработка всего Python-кода | [processing_report.json](checks/code_cleanup/processing_report.json) |
| Scope и ограничения обработки skill'ом | [skill_application.json](checks/code_cleanup/skill_application.json) |
| Финальные хеши исходников после ручной правки | [final_state.json](checks/final_state.json) |
| Проверка готового учебного пакета | [final_verification.json](checks/final_verification.json) |

Последний mini-eval: [сырые результаты](../data/evaluations/graph_eval_20261125_152620_112169.json), [AI-assisted разбор](../data/evaluations/graph_eval_20261125_152620_112169.review.json). Это маленькая development-проверка, не независимый benchmark.

## Повторение проверок

Из корня проекта; команды ниже не выполняют ingestion, миграции или генерацию:

```bash
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B review/tools/verify_package.py
```

Для нового снимка БД и проверок требуется работающий Neo4j и локальный кэш embedding-модели:

```bash
.venv/bin/python -B review/tools/collect_checks.py --output review/checks_repeat
```

Выбирай новую папку: сборщик намеренно не перезаписывает старые результаты. Для обычной повторной проверки не нужен `--watermark-tool-root`: отдельная обработка внешним инструментом уже завершена.

`verify_package.py` проверяет материалы, колоду и сохранённые свидетельства, но не оценивает заново качество LLM. Генерация `.apkg` использует отдельное временное окружение; зависимости приложения не менялись.

### Что находится в `review/tools/`

| Инструмент | Назначение |
|---|---|
| `collect_checks.py` | Read-only снимок данных/БД, syntax, API mocks, token budget, unit-тесты и source manifest |
| `collect_extra_evidence.py` | Offline-примеры слабой схемы, версии core dependencies, пересчёт Laya и сверка исходников; существующий результат не перезаписывает |
| `export_anki.py` | JSON → TSV и optional APKG с экранированием HTML и стабильными IDs |
| `verify_package.py` | Повторные тесты, ZIP/SQLite-структура колоды, совпадение экспортов, ссылки, числа и SHA-256 |

## Важное перед публикацией

В аудированном срезе были захардкоженные учётные данные Neo4j; исторические замечания в разборе относятся к нему. Перед публикацией пароль вынесен в переменную `NEO4J_PASSWORD`; `.env`, новые backups и логи исключены из Git. Смена пароля в самой БД не выполнялась. Файлы для публикации выбираются явно; не делай `git add -A` вслепую.
