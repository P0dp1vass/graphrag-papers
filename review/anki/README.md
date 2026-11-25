# Анки: GraphRAG Papers

**154 карточки**, из них **83 основные** с тегом `priority::core`. Вопросы и объяснения на русском, имена API/моделей сохранены. Одна карточка → один вопрос; не нужно учить целый доклад как один ответ.

После отдельного прохода код отформатирован без изменения логики, затем автор вручную убрал docstrings и комментарии из `scripts/*.py` (актуальные хеши — [final_state.json](../checks/final_state.json)). Большинство номеров строк в карточках указывает на первичный аудированный срез; текущие позиции можно найти по имени функции или через [карту строк](../checks/code_cleanup/line_map.json).

## Импорт — рекомендуемый способ

Открой в Anki **Файл → Импорт** и выбери:

**[graphrag_review_ru.apkg](graphrag_review_ru.apkg)**

Пакет создаёт колоду `GraphRAG Papers — Review RU` и тип заметки `GraphRAG Review RU`. На лицевой стороне вопрос, на обороте ответ и ссылка-указатель на исходник. Это одна обычная карточка на заметку, без обратных карточек и медиа. Стабильный ID и GUID позволяют обновлять пакет, сохраняя идентичность заметок; перед массовым обновлением своей колоды всё равно сделай backup.

`.apkg` проверен по ZIP/SQLite: 154 notes и 154 cards. Интерактивный импорт в установленном Anki здесь не запускался.

## Альтернатива — TSV

[graphrag_review_ru.tsv](graphrag_review_ru.tsv) — UTF-8, разделитель Tab:

1. Выбери стандартный тип «Основная» / `Basic` (один вопрос и ответ).
2. Первая колонка → Front, вторая → Back, третья → Tags.
3. Включи HTML в полях; в файле есть `#html:true` и указание tags column.
4. Укажи свою колоду назначения и проверь preview импорта.

**Выбирай APKG или TSV, не оба:** типы заметок и ключи дедупликации разные, импорт обоих может дать дубли.

## Как учить

- Начни с основных: в браузере Anki поиск `tag:priority::core tag:graphrag_review`.
- Темы: `architecture`, `python`, `http`, `ingestion`, `validation`, `neo4j`, `provenance`, `entities`, `migration`, `embeddings`, `retrieval`, `generation`, `api`, `evaluation`, `laya`, `security`, `testing`, `reproducibility`, `review`.
- Перед чтением ответа проговори объяснение вслух и попробуй указать функцию в коде.
- Если ответ неверный — сначала разберись по source, потом повтори; не заучивай только числа.
- Начни с 15–25 новых в день и регулярных повторений. При нехватке времени выбери core, не пытайся «закрыть» все 154 сразу.
- Числа относятся к снимку 2026-11-25. Состояние БД и результаты нового eval могут измениться.

Карточки не заменяют [walkthrough](../CODE_WALKTHROUGH_RU.md) и [репетицию выступления](../REVIEW_PRESENTATION_RU.md). Метрики Laya и GraphRAG отражают малые development-проверки с AI-assisted разметкой/оценкой.

## Источник и пересборка

- [cards.json](cards.json) — редактируемый источник с устойчивыми IDs, вопросом `q`, ответом `a`, указателем `source`, тегами.
- [export_manifest.json](export_manifest.json) — число карточек и SHA-256 исходника/экспортов.
- [export_anki.py](../tools/export_anki.py) — экранирует HTML, проверяет уникальность, создаёт TSV/APKG.

TSV создаётся стандартной библиотекой:

```bash
.venv/bin/python -B review/tools/export_anki.py
```

Для APKG нужен отдельный интерпретатор с `genanki==0.13.1`; при подготовке использовалось временное окружение, не зависимости приложения:

```bash
uv venv /tmp/opencode/graphrag-review-export
uv pip install --python /tmp/opencode/graphrag-review-export/bin/python genanki==0.13.1
/tmp/opencode/graphrag-review-export/bin/python -B review/tools/export_anki.py --apkg
.venv/bin/python -B review/tools/verify_package.py
```

Если временное окружение уже есть, повторное создание не требуется. После изменения JSON пересобирай **оба** формата через `--apkg`, иначе старый APKG не будет соответствовать новому TSV.
