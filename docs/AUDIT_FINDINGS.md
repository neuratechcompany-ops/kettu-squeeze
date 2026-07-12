# Audit Findings — Kettu Squeeze v0.1.0

## FINDING-001: JSON null-stripping is lossy, marked as lossless
- **ID:** FINDING-001
- **Severity:** MEDIUM
- **Component:** `compressors/__init__.py` — JsonCompressor
- **Description:** `strip_nulls=True` (default) удаляет ключи со значением `null`. `{"field": null}` → `{}`. В JSON Schema, OpenAPI, GraphQL `null` несёт семантическую нагрузку (явное отсутствие значения ≠ отсутствие ключа).
- **Reproduction:**
  ```python
  JsonCompressor().compress('{"field": null}', artifact, policy_with_strip_nulls=True)
  # → "{}"
  ```
- **Impact:** Агент может неверно интерпретировать API-ответы и конфигурации.
- **Root cause:** `_strip_nulls` удаляет `k if v is None` без сохранения recoverable ref.
- **Fix:** Заменить `null`-значения на recoverable refs: `{"field": "[null, ref=artifact:...]"}` ИЛИ маркировать режим как `recoverable_lossy` при strip_nulls=True.
- **Regression test:** `tests/test_core.py::TestJsonCompressor::test_strip_nulls_semantic_preservation`
- **Status:** FIXED

## FINDING-002: GPT-OSS coverage reported as complete (100%) but is 90.9%
- **ID:** FINDING-002
- **Severity:** MEDIUM
- **Component:** benchmarks/portability.py, benchmarks/reports/portability_gptoss.json
- **Description:** Отчёт "Portability Gate: PASS" и "10/10 PASS" не указывает, что `long_session_200` исключён. Полное покрытие — 10/11 = 90.9%.
- **Reproduction:** `len(_read_scenario_data()) == 11`, portability.json содержит 10 уникальных scenario_id.
- **Impact:** Пользователь может предположить, что GPT-OSS протестирован на всех сценариях.
- **Root cause:** `portability.py` фильтрует `long_session` без явного указания в отчёте.
- **Fix:** Добавить в отчёт строку `Coverage: 10/11 (90.9%), long_session_200 skipped (400+ model calls)`.
- **Regression test:** проверка вывода `generate_portability_report` на наличие coverage percentage.
- **Status:** FIXED

## FINDING-003: Negative line range silently clamped
- **ID:** FINDING-003
- **Severity:** LOW
- **Component:** `artifact_store/__init__.py` — `get_range()`
- **Description:** `artifact:<id>:L-1-L5` → start_line=-1 silently clamped to 1 вместо rejected.
- **Reproduction:** `store.get_range(id, -1, 5)` → возвращает L1-L5 без ошибки.
- **Impact:** Тихое искажение запроса — агент получает не те строки, которые запросил.
- **Root cause:** `if start_line < 1: start_line = 1` без warning.
- **Fix:** Возвращать ошибку при отрицательных значениях.
- **Regression test:** `test_get_range_negative_rejected`
- **Status:** FIXED

## FINDING-004: OOB range returns empty string silently
- **ID:** FINDING-004
- **Severity:** LOW
- **Component:** `artifact_store/__init__.py` — `get_range()`
- **Description:** `artifact:<id>:L100-L200` при 3 строках возвращает `""` без indication.
- **Impact:** Агент может интерпретировать пустой ответ как "файл пуст".
- **Fix:** Возвращать последние N строк или явную ошибку.
- **Status:** KNOWN LIMITATION — возврат пустой строки задокументирован.

## FINDING-005: JSONL runs appended, not clean per-session
- **ID:** FINDING-005
- **Severity:** LOW
- **Component:** `benchmarks/agent_eval.py` — `_write_run`
- **Description:** `runs.jsonl` открывается в режиме `"a"` (append). Повторные запуски накапливают дубликаты (44 записи вместо 22).
- **Impact:** Затрудняет воспроизводимость.
- **Fix:** Использовать `"w"` при первом запуске или timestamp-based filename.
- **Status:** KNOWN LIMITATION — append mode полезен для multi-run сессий.

## FINDING-006: Herpes agent forwarding interferes with port 8080
- **ID:** FINDING-006
- **Severity:** INFO
- **Component:** infrastructure
- **Description:** `curl localhost:8080/v1/models` возвращает 302 (перенаправление Hermes), а не список моделей llama.cpp.
- **Impact:** Путаница при отладке.
- **Status:** INFO — не дефект кода, задокументировано в памяти.

## FINDING-007: No tokenizer_id in benchmark results
- **ID:** FINDING-007
- **Severity:** LOW
- **Component:** все benchmark модули
- **Description:** Token counts используют `tiktoken.get_encoding("cl100k_base")` или heuristic `len//3`, но benchmark outputs не сохраняют tokenizer_id.
- **Impact:** Невозможно воспроизвести token counts на другом tokenizer.
- **Fix:** Добавить `tokenizer_id` в JSONL и reports.
- **Regression test:** проверка наличия `tokenizer_id` в runs.jsonl.
- **Status:** FIXED
