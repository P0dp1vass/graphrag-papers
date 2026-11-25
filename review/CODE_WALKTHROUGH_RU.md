# Разбор кода: от входного файла до ответа API

Читать из корня репозитория. Диапазоны строк относятся к исходникам на дату аудита; они не исправлялись при подготовке этих материалов. Значения паролей намеренно не цитируются.

Позже по отдельному запросу выполнены форматирование и редактура комментариев без изменения AST/строковых значений, а затем автор вручную убрал docstrings и комментарии из `scripts/*.py`. Диапазоны ниже и цитаты сохранены как ссылки на аудированный срез; актуальные хеши — в [final_state.json](checks/final_state.json), соответствие строк — в [line_map.json](checks/code_cleanup/line_map.json).

## 1. Базовые понятия Python, которые стоит уметь объяснить

- **`dict`** хранит ключ → значение; в проекте через словари передаются статьи, тройки и результаты. `dict` не является проверенной схемой данных.
- **`list`** — упорядоченная коллекция, допускает дубли. **`set`** — множество уникальных hashable-элементов; удобно для done IDs и объединения источников.
- **`tuple`** — неизменяемая последовательность; подходит для ключа `(head, relation, tail)`.
- **`list[dict]`, `-> str`** — type hints. Обычная функция Python не начинает проверять их во время исполнения. Pydantic делает runtime validation только там, где модель действительно используется.
- **Comprehension** — компактное создание коллекции. Например, `[p["id"] for p in papers]` собирает IDs без изменения исходных статей.
- **`dict.get(key, default)`** подставляет default при отсутствии ключа, но не заменяет явно переданный `None`. Поэтому `.get("entities", [])` не спасает от `"entities": null`.
- **`{**rec, "entities": ...}`** — новый словарь с поверхностным копированием; вложенные объекты не копируются рекурсивно.
- **`with`** использует context manager для освобождения ресурсов. Это относится к открытым файлам, driver и session.
- **`try/finally`** исполняет cleanup и при исключении. Код после `yield` без `finally` не гарантирует cleanup при провале до `yield`.
- **`if __name__ == "__main__"`** отделяет прямой запуск от импорта. Импорт функции в тест не запускает demo-блок.
- **`SystemExit`** наследуется от `BaseException`, а не от `Exception`. Для библиотечного кода здесь удобнее обычное типизированное исключение.
- **`*` в параметрах**, как в `use_graph`, требует передавать следующие аргументы по имени. Это делает экспериментальный режим заметным в вызове.
- **Mock** заменяет зависимость управляемым объектом. Он проверяет логику вызовов, но не поведение настоящего сервиса.

## 2. `scripts/fetch_papers.py` — получить корпус

**Вход:** `limit`; **выход:** список `{id, title, abstract}` и при прямом запуске `data/papers.json`.

`fetch_papers` (`5–26`) отправляет GET на arXiv Atom API: категория `cs.CL`, новые статьи первыми, `max_results=limit`. `timeout=30` предотвращает бесконечное ожидание; `raise_for_status()` превращает HTTP 4xx/5xx в исключение.

Далее XML разбирается ElementTree. Префикс `a` привязан к Atom namespace; без него `findall("entry")` не найдёт элементы в namespace. `" ".join(text.split())` нормализует переносы/пробелы. Фильтр `len(abstract) >= 300` — число символов Python-строки, не число слов или model tokens.

**Сильное:** простой источник и нормализация. **Слабое:** нет пагинации, retry/backoff и проверки отсутствующих XML-элементов; используется HTTP URL; фиксированный сортированный срез смещает корпус к свежим статьям. `max_results` не обещает столько же статей после фильтра.

**На ревью:** «Я использую API, а не PDF parser. Поэтому все дальнейшие утверждения ограничены содержимым abstracts».

## 3. `scripts/extract_triplets.py` — получить структуру из текста

**Вход:** abstract; **выход:** `{"entities": [...], "relations": [...]}`.

### Prompt и HTTP (`7–21`, `37–56`)

System prompt задаёт JSON-схему, семь допустимых предикатов и требование endpoints из entities. Это инструкции модели, а не принудительная runtime-схема. В Ollama уходит Qwen, `stream=False`, `temperature=0`. Поиск и QA английские, но исторический system prompt extraction русскоязычный — не нужно выдавать весь pipeline за исключительно англоязычный код.

Две попытки ловят HTTP/сетевые ошибки и JSONDecodeError. `json.loads` проверяет синтаксис JSON, не значение и не правильность отношений. `KeyError`, `TypeError`, `AttributeError` структурного разбора здесь не обрабатываются. После двух неудач выбрасывается `SystemExit`.

### `validate_triplets` (`23–35`)

1. Берёт множество entities.
2. Отбрасывает relation с пустым или отсутствующим endpoint либо endpoint вне entities.
3. Подменяет неизвестный relation на `RELATED_TO`.
4. Оставляет только реально использованные entities, сортирует их.

**Зачем удалять неиспользованные entities:** упрощает граф вокруг связей. **Цена:** может потерять полезные одиночные сущности, если они не вошли ни в одну тройку.

**Важно:** функция не проверяет, что все entities — строки и relations — объекты нужной формы. В `extra_evidence.json` есть воспроизведения, а не предположение.

**Как улучшать:** сначала строгая структура и отчёт rejects; отдельно semantic entailment: действительно ли abstract поддерживает именно этот предикат и это направление?

## 4. `scripts/extraction.py` — цикл и resume

**Вход:** `papers.json`; **выход:** append в `triplets.jsonl`.

`load_done_ids` (`8–16`) читает уже существующие записи. `main` (`18–35`) пропускает IDs, известные при старте, вызывает extractor, ловит его `SystemExit` и сохраняет результат.

**JSONL:** одна JSON-запись на строку, удобно дописывать и читать потоково. Однако текущий скрипт держит список papers в памяти и не имеет журналирования состояния.

Нельзя говорить «resume полностью надёжен»: done не обновляется внутри цикла, нет lock, tail recovery, fsync и версий extraction. Авария записи может оставить неполную последнюю строку, на которой следующий запуск упадёт. Существующие дубли не надо автоматически удалять без сравнения их содержания.

## 5. `scripts/entity_names.py` — явный словарь алиасов

Весь файл (`1–6`): `ALIASES` и `canonicalize_entity`. Сейчас ровно одно подтверждённое соответствие `ACTGCG → ActGCG`.

`ALIASES.get(name, name)` возвращает каноническую форму либо исходное имя. Нет lowercasing всех сущностей, fuzzy matching, learned entity linking. Это осознанно узкое правило.

Применять одинаково к списку сущностей, head и tail обязательно, иначе можно создать связи на несуществующие/дублирующиеся узлы. Но изменение словаря не мигрирует уже записанные данные — для этого отдельный скрипт.

## 6. `scripts/load_graph.py` — записать граф

**Вход:** `triplets.jsonl`; **выход:** Neo4j.

| Функция | Строки | Смысл |
|---|---:|---|
| `_add_paper` | 8–11 | `MERGE` Paper по ID, обновление title |
| `_add_entity` | 13–14 | `MERGE` Entity по name |
| `_add_relation` | 16–28 | направленный `R` с type и source IDs |
| `_mention` | 30–36 | Paper → Entity через MENTIONS |
| `create_constraints` | 38–51 | уникальность Paper.id и Entity.name |
| `load_triplets` | 53–71 | цикл записей и отдельные write-транзакции |

### Мини-словарь Cypher

- **`MATCH`** ищет существующий pattern; если endpoints не найдены, запись может не создаться.
- **`MERGE`** ищет совпадающий pattern либо создаёт. Это не «обновить весь объект» и не «доказать истинность».
- **`SET`** записывает свойства. `SET e = $properties` заменяет карту свойств, а `SET e.embedding = ...` — отдельное поле.
- **`$pid`, `$head`** — параметры. Значения не конкатенируются в текст запроса, что отделяет данные от Cypher.
- **`UNWIND`** превращает список параметров в строки внутри запроса — полезно для batch.
- **`coalesce(x, [])`** заменяет null на пустой список; `CASE` не добавляет source ID второй раз.
- **`.consume()`** полностью потребляет result и позволяет явно завершить запрос/получить summary; **`.data()`** материализует строки словарями; **`.single()`** ожидает одну строку.
- **Driver** управляет соединениями; **session** — контекст работы; **transaction** — атомарная единица изменений.

Текущий код делает много `session.execute_write`. Каждая такая callback-транзакция атомарна отдельно, но вся статья — нет. Managed transaction callback может повторяться драйвером при подходящих временных ошибках: не следует добавлять туда внешние неидемпотентные побочные эффекты.

`MERGE` и constraints помогают повторной загрузке, но не удаляют факты предыдущей версии extraction и не заменяют версионирование. Абстракты здесь не загружаются.

## 7. `scripts/add_abstracts.py` — дополнить Paper

`add_abstracts` (`5–14`) делает один `UNWIND $papers`, находит существующие Paper по ID, пишет abstract и возвращает count. `MATCH` не создаст две отсутствующие статьи сам.

Разделение шагов объясняет, почему наличие `papers.json` не гарантирует, что любой Paper уже имеет abstract. В текущем снимке все 498 имеют его; это проверено запросом, а не выведено из наличия скрипта.

## 8. `scripts/embeddings.py` — векторное представление

- `create_index` (`9–19`) создаёт **entity_vec**, cosine, размерность передаётся параметром.
- `embed_entities` (`21–35`) кодирует только names сущностей.
- `embed_papers` (`37–54`) кодирует `title + ". " + abstract`, найденный по ID во входном JSON.
- Main (`56–63`) задаёт 384 измерения и вызывает обе записи.

`model.encode` выдаёт числовые массивы; `.tolist()` преобразует их в сериализуемые Python-списки для Neo4j driver. `zip` сопоставляет входы и vectors по позиции; при несовпадении длин `zip` молча остановится на более короткой коллекции — полезен дополнительный assert.

**Embedding** — фиксированный по размеру вектор смысла, не сжатый текст с гарантией сохранения каждого факта. **Cosine similarity** сравнивает направления векторов; score не является probability правильного ответа.

Здесь нет `.abstract` update и создания paper_vec. Полный запуск поиска требует ещё `add_abstracts.py` и `qa.create_paper_index`. Новый embedding model требует согласованного пересчёта вопросов и корпуса; совпадения размерности недостаточно.

## 9. `scripts/retrieval.py` — английский title-aware/dense retrieval

### `extract_title_terms` (`14–27`)

Regex выделяет латинские tokens с цифрами/разделителями. Кандидат — минимум две uppercase-буквы, дефис или underscore, затем lowercasing, исключение generic terms, дедупликация, максимум 10.

Это эвристический detector названий, не полноценная NLP-модель и не распознавание всех имён.

### `title_pattern` (`30–33`)

Разбивает идентификатор на части, экранирует каждую через `re.escape` и разрешает разделители. Границы `\b` уменьшают случайные совпадения внутри более длинных слов. Пример: `RAG-FGO` может найти вариант с пробелом/underscore.

### `rank_candidates` (`36–47`)

Словарь по paper ID объединяет vector_hits и title_hits. Title-запись заменяет совпавшую vector-запись. Сортировка: больше matched names → выше score → ID для устойчивого tie-break. В финале `[:k]`.

Нет сложения rank scores, как в RRF. Приоритет имени абсолютный в рамках этого правила: высокое cosine без title match может проиграть более слабому cosine с совпадением.

### `retrieve_papers` (`50–91`)

1. Проверяет `k >= 1`.
2. ANN-запрос в `paper_vec`.
3. Если identifier terms нет — возвращает vector hits.
4. Иначе сканирует title всех подходящих Paper regex-параметрами, для matches считает cosine.
5. Объединяет оба набора.

На 500 статьях scan приемлем как простое исправление. При росте корпуса — full-text/candidate index и измерение latency. `ANN` — approximate nearest neighbours: индекс ускоряет поиск ценой возможных пропусков; title supplement адресует часть конкретных пропусков.

## 10. `scripts/qa.py` — центральный online pipeline

### Константы и «неиспользуемый путь»

Generation options (`14–19`): temperature 0, seed 42, num_ctx 8192, num_predict 256. Контекстный бюджет и лимит выхода — не одно и то же. `TOP_K = 5` сейчас не задаёт paper top-k: в `prepare_context` явно стоит **3**.

`vector_search_entities` (`21–28`) присутствует, но текущий ask её не вызывает. `create_paper_index` (`51–61`) нужен для paper_vec, но API сам его не создаёт.

### `graph_context` (`30–49`)

Pattern: Paper → упомянутая head Entity → исходящее R → tail Entity. Дополнительно требуется ID Paper в `r.source_ids`; затем distinct sources, сортировка и лимит 30. Форматируются строки `head -rel-> tail (sources: ...)`.

Здесь нет relevance score связи, второго hop или дополнительных документов. Детерминированная сортировка полезна для сравнения prompt-пар, но не гарантирует лучшие 30 фактов.

### `prepare_context` (`63–70`)

Кодирует вопрос, открывает session, получает top-3, извлекает graph facts при `use_graph=True`. Возвращает словарь с papers и facts. Разделение retrieval и generation позволяет eval заморозить одинаковый контекст.

### `build_prompt` (`73–99`)

Собирает правила, автоматические relations, URL/title/abstract каждой статьи и вопрос. Требует английский краткий ответ, URL, отказ при нехватке evidence и неисполнение инструкций из sources.

Prompt — полезный защитный слой, но не формальная защита от injection и не гарантия цитирования. Результаты mini-eval показывают, что требование URL часто игнорируется.

### `generate_answer` (`102–129`)

POST в Ollama с timeout 180, HTTP status check, чтение message content, отклонение пустого ответа, timing через monotonic `perf_counter`. Возвращает answer, wall_seconds, output truncation и subset Ollama metadata.

`done_reason == "length"` указывает ограничение выхода, но отсутствие такого флага не доказывает, что весь input был виден модели. В ответе могут быть корректные usage и неверные числа.

### `ask` (`132–137`)

Оркестратор: context → prompt → generation; возвращает **только строку**. Это сохраняет API, но теряет diagnostics на обычном пути. Если расширять contract, лучше явно спроектировать internal result и публичный response, а не случайно сломать клиентов.

## 11. `scripts/app.py` — API, lifecycle, модели

`AskRequest` (`12–13`) и `AskResponse` (`15–17`) задают базовую структуру. Входной `str` не запрещает `""`, пробелы и длинный текст; настройка extra не задана.

`lifespan` (`19–25`) создаёт driver, проверяет соединение, загружает SentenceTransformer один раз, хранит в `app.state`; это лучше, чем грузить модель на каждый запрос. Но cleanup нужен через `try/finally`, включая ошибку до `yield`.

`/health` (`29–31`) — константная liveness. `/ask` (`33–36`) синхронно вызывает QA и возвращает question/answer. Сервис ещё зависит от индексов и Ollama, хотя health может отвечать OK.

**HTTP-основа:** 200 — успешная обработка; 422 — ошибка модели входа; 405 — неверный метод; 5xx — сервер/зависимость. В mock-проверке 200 означает «контракт пропустил запрос», не «Qwen ответил верно».

Не стоит обещать production throughput: модель, GPU, threadpool, pool соединений и очередь запросов нужно измерять.

## 12. `scripts/backup_relations.py` — частичный backup

`7–25`: read session извлекает head/tail/properties всех R, затем пишет новый timestamp JSON через режим `"x"`, защищающий от перезаписи.

Это **backup слоя отношений**, а не полный Neo4j backup: нет всех Paper/Entity, embeddings, MENTIONS, constraints и indexes. Нельзя восстановить полную БД на пустом сервере только этим файлом.

## 13. `scripts/rebuild_relations.py` — destructive maintenance

`rebuild` (`6–29`) удаляет все R между Entity, создаёт их из подготовленного списка и сверяет processed count. Внутри одной managed transaction ошибка должна откатить удаление.

Main (`31–57`) проверяет существующий фиксированный backup только на непустоту, а данные восстановления берёт из текущего JSONL и canonical mapping. Это пересборка из source, а не restore свойств backup.

**На ревью:** файл стоит показывать как обнаруженный operational risk, а не запускать. Backup без проверенного restore недостаточен.

## 14. `scripts/merge_actgcg.py` — безопасная узкая миграция

| Блок | Строки | Инвариант |
|---|---:|---|
| `snapshot` | 19–45 | оба узла и все incident edges с properties |
| `merge_edge_properties` | 48–63 | union источников, отказ при конфликте |
| `edge_key` | 66–72 | head/kind/predicate/tail, направление сохранено |
| `build_plan` | 75–146 | approved alias, нужные labels, canonical embedding |
| `apply_plan` | 149–227 | свежесть snapshot, только backed-up edges, post-check |
| `main` | 230–266 | default dry-run, `--apply`, durable backup до write |

План строится чистой функцией, поэтому хорошо тестируется без Neo4j. Объединение sources использует set, сортирует результат; совпавшие рёбра группируются с учётом направления и predicate. Canonical embedding не усредняется с alias.

Перед изменениями snapshot перепроверяется; неожиданные связи не удаляются через `DETACH DELETE`, а вызывают отказ/rollback. После сравниваются свойства и рёбра. Это снижает риск, но не заменяет отдельный tested restore и полноценный backup на случай сбоя среды.

Повторный запуск при отсутствии alias — no-op, если canonical существует. Логика специально ограничена двумя именами, это не общий entity-resolution engine.

## 15. `scripts/eval.py` — исторический baseline

`ask_baseline` (`20–29`) вызывает LLM без retrieved context. Main (`42–60`) сравнивает её с QA на пяти русских вопросах, пишет `eval_results.json`, печатает случайные тройки.

Это ранний sanity check: разные контексты/инструкции и отсутствие формальной оценки смешивают несколько причин. Не использовать как доказательство эффекта графа; не путать с английским `eval_graph.py`. Исторический файл сохранён, но текущая продуктовая цель — английский QA.

## 16. `scripts/eval_graph.py` — controlled development ablation

- Cases (`34–85`): четыре answerable и один отказ, есть expected sources и reference notes.
- Citation diagnostics (`88–105`): распознаёт arXiv URLs, проверяет membership. Versionless URL разрешается для найденной статьи; другая explicit version не предполагается эквивалентной.
- `summarize` (`108–139`): считает completion/errors/truncation/URL/timing, не выдумывает correctness.
- `save_report` (`142–148`): пишет temporary и replace; это защита от частичной основной JSON-записи, но не система координации параллельных writers.
- `prepare_cases` (`151–168`): один retrieval snapshot на вопрос; expected/reference metadata не передаются в generator.
- `run_answers` (`171–203`): чередует порядок режимов, сохраняет prompt и diagnostics после каждого ответа; failed call остаётся ошибкой, а не abstention.
- Main (`206–263`): новые timestamp reports, запрет случайной перезаписи, resume с проверкой model/options.

**Нюанс resume:** уже сохранённый mode пропускается, в том числе error entry; команда не является автоматическим retry всех ошибок. Проверка model/options не проверяет весь source hash или версии библиотек — для строгого эксперимента нужен полный provenance manifest.

## 17. Четыре Laya-скрипта

### `scripts/laya_filter.py`

`9–15` задаёт `noul`; `22–49` проверяет каждую relation, оставляет score ≥0.5, удаляет неиспользованные entities, пишет `triplets_filtered.jsonl`. Файл открывается с `"w"` — предыдущий результат перезаписывается. При падении возможен частичный output, resume отсутствует.

Это отдельный экспериментальный путь: canonical graph loader всё ещё читает исходный файл. Порог 0.5 не становится «50% вероятностью истинности» без калибровки.

### `scripts/check_laya.py`

Четыре вручную подобранных контрастных примера: поддержка USES против необоснованного IMPROVES, outperform против EXTENDS. Печатает prediction и expected; это smoke test, не репрезентативная оценка.

### `scripts/prepare_laya_eval.py`

`8–26` дедуплицирует по `(paper_id, head, relation, tail)`, добавляет abstract и `expected=None`. `27–37` сортирует кандидатов, использует локальный RNG seed 42, берёт до 20 и пишет annotation file.

Случайный seed делает выборку повторяемой при одинаковом входе, но не автоматически сбалансированной. Режим `"x"` при записи защищает существующую ручную разметку: повторный запуск завершится FileExistsError, а не перезапишет файл. Для новой выборки нужен отдельный путь или осознанно сохранённая предыдущая версия.

### `scripts/eval_laya.py`

`4–12` переводит predicatе в фразу; `18–32` задаёт A/B question; `34–63` пропускает U, получает choice/probabilities; `64–86` считает confusion matrix и пишет report.

Не сохраняет usage.truncated/full prompt/model revision. Для объяснения слабых метрик нельзя просто обвинить модель: нужны явные онтологические правила, независимая разметка и проверка token budget. Описанные в полном разборе числа пересчитаны из сохранённых результатов, новый inference в аудите не запускался.

## 18. Тесты: что доказано, а что нет

| Файл | Что проверяет | Чего не доказывает |
|---|---|---|
| `tests/test_retrieval.py` | identifiers/regex, ranking, supplement ANN, k validation с fake session | реальную Cypher-совместимость, качество на новом корпусе |
| `tests/test_merge_actgcg.py` | plan, направления, union provenance, конфликты, no-op, canonical embedding | реальную конкуренцию транзакций, restore на сервере |
| `tests/test_eval_graph.py` | одинаковые inputs, no leakage, mode order, resume, diagnostics, errors | семантическую правильность ответов Qwen |

Всего **36** успешных тестов. Нет измерения coverage и нет основания называть это полным integration suite. API mock probes сохранены в audit tools, но ещё не интегрированы в постоянный regression suite проекта.

**Нужные следующие тесты:** malformed extraction, crash/resume JSONL, Neo4j integration на временной БД, startup cleanup, empty/long question, HTTP failures/timeouts, ingest idempotency и полный end-to-end smoke.

## 19. `src/`, packaging и root config

- **`src/graphrag_papers/__init__.py`**: docstring и `main`, печатающий строку. Именно сюда ссылается `[project.scripts]`; это не рабочий orchestration CLI.
- **`src/__init__.py`**: другая Hello-world заглушка; реальная логика от неё не зависит.
- **`pyproject.toml`**: Python ≥3.12, основные пять прямых dependencies, uv_build backend. Нижние границы версий допускают будущие обновления, а `uv.lock` фиксирует конкретное разрешение.
- **`uv.lock`**: generated lock с hashes/distributions/transitive packages. Его не нужно пересказывать построчно; важно понимать роль, не редактировать вручную и использовать frozen/synced install. Это не lock модельных весов и внешних серверов.
- **`.python-version`**: 3.12 для выбора интерпретатора; не то же, что допустимый диапазон `requires-python`.
- **`.gitignore`**: Python artifacts и venv; пока нет политики данных, logs, backups и secrets.
- **Корневой `README.md`**: пустой. Эти review-документы помогают учиться, но не заменяют будущую обычную инструкцию установки для пользователя репозитория.

Все 19 рабочих скриптов, оба `src`-файла и три test-файла описаны выше. `.venv`, кэши, `.git`, corpus и vendored skill не считаются нашим функциональным Python-кодом.

### Данные и служебные артефакты

| Путь | Роль и оговорка |
|---|---|
| `data/papers.json` | Исходный snapshot title/abstract/ID; не полный текст статей |
| `data/triplets.jsonl` | Автоматическая extraction, текущий источник загрузчика; содержит повторные IDs |
| `data/triplets_filtered.jsonl` | Результат старого experimental Laya filter; не источник активного loader |
| `data/laya_eval.json` | Небольшая AI-assisted разметка, включая U |
| `data/laya_eval_results.json` | Сохранённые predictions/metrics; без полной телеметрии truncation |
| `data/eval_results.json` | Старое сравнение baseline с QA на русских вопросах |
| `data/evaluations/` | Новый frozen-context mini-eval и отдельное AI-assisted review |
| `data/backups/` | Частичный backup R и snapshot до слияния ActGCG; не полная резервная копия сервера |
| `extraction.log` | Исторический диагностический вывод, не источник истины о текущей БД и не надёжный job ledger |
| `.agents/skills/remove-ai-marks/` | Локальная копия внешнего skill с выключенным autoinvoke; installation provenance в `INSTALLATION.json` |
| `review/` | Этот учебный пакет и read-only проверки, не новая бизнес-логика GraphRAG |

## 20. Карта для быстрого ответа «покажи в коде»

| Вопрос | Открыть |
|---|---|
| Откуда берутся статьи? | `scripts/fetch_papers.py:5` |
| Где проверяется тройка? | `scripts/extract_triplets.py:23` |
| Где направление и sources? | `scripts/load_graph.py:16` |
| Почему не берём чужие факты? | `scripts/qa.py:30` |
| Как работает исправление RAG-FGO? | `scripts/retrieval.py:50` |
| Где top-k? | `scripts/qa.py:67` |
| Что видит генератор? | `scripts/qa.py:73` |
| Откуда latency/usage? | `scripts/qa.py:102` |
| Где API и startup? | `scripts/app.py:19` |
| Где безопасная канонизация? | `scripts/merge_actgcg.py:75` |
| Как изолирован эффект графа? | `scripts/eval_graph.py:151` |
| Почему Laya не обязательна? | `scripts/laya_filter.py:22` и `scripts/load_graph.py:54` |
