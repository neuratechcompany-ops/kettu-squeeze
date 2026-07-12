# Claims Audit — Kettu Squeeze v0.1.0

Каждое публичное заявление проекта проверено против кода, тестов и benchmark outputs.

| # | Заявление | Источник | Доказательство | Статус |
|---|-----------|----------|---------------|--------|
| 1 | 88 тестов проходят | README/report | `pytest -q`: 88 passed, 1 skipped | ✅ VERIFIED |
| 2 | COS 96.1 EXCELLENT | COS report | `EvalRunner.run_full()`: 96.1, hard gates clean | ✅ VERIFIED |
| 3 | Byte-exact recovery 100% | COS report | `expand()` возвращает byte-identical контент | ✅ VERIFIED |
| 4 | No cross-session refs | README/invariants | Session B context пуст после записи в A | ✅ VERIFIED |
| 5 | Quality delta 0% (DeepSeek) | Phase 4 report | 11 сценариев, RAW=SQUEEZE=100% recall | ✅ VERIFIED |
| 6 | GPT-OSS portability PASS | Phase 5 report | 10/10 сценариев RAW=SQUEEZE=100% | ⚠️ COVERAGE 90.9% |
| 7 | Unicode safe | README/invariants | 25 Unicode fixtures, 0 panics | ✅ VERIFIED |
| 8 | Broken refs = 0 | COS report | Все refs expandable | ✅ VERIFIED |
| 9 | Verifier on all paths | Architecture | engine.compress → verify всегда | ✅ VERIFIED |
| 10 | Source code never lossy | README | STRICT_RAW default для .py/.rs/.js | ✅ VERIFIED |
| 11 | quality_measured = true | Phase 4 | self-evaluation + GPT-OSS API calls | ✅ VERIFIED |
| 12 | Lossless by default | README | CompressionMode.LOSSLESS default | ⚠️ null-stripping is lossy |
| 13 | Recoverable omissions | README | `[omitted: N lines, ref=...]` формат | ✅ VERIFIED |
| 14 | Session-aware references | invariants | context ledger scoped by session_id | ✅ VERIFIED |
| 15 | MCP ready | README | 6 tools, stdio transport, FastMCP | ✅ VERIFIED |
| 16 | NAB computed | Phase 4 | DeepSeek NAB +0.011, GPT-OSS NAB +0.012 | ✅ VERIFIED |

## Найденные расхождения

### CLAIM-006: GPT-OSS coverage
- **Заявлено:** "10/10 PASS" — подразумевает полное покрытие
- **Факт:** 10 из 11 сценариев (90.9%), `long_session_200` исключён
- **Severity:** MEDIUM — отчёт вводит в заблуждение
- **Исправление:** явно указать coverage percentage и причину исключения

### CLAIM-012: null-stripping как lossless
- **Заявлено:** JSON compressor mode = lossless
- **Факт:** `{"field": null}` → `{}` меняет семантику
- **Severity:** MEDIUM — `null` в JSON Schema/OpenAPI несёт значение
- **Исправление:** маркировать null-stripping как `recoverable_lossy`, либо сохранять nulls с `"field": null`
