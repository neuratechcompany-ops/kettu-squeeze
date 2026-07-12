# Kettu Squeeze — Invariants

Нерушимые гарантии, нарушение которых означает FAIL релиза.

## 1. Immutable Raw Artifact

> Raw artifact is immutable. Once written, it can never be modified or deleted automatically.

- Append-only хранилище
- Никакая компрессия не удаляет исходник
- Любое сжатое представление ссылается на raw artifact
- Restore возможен в любой момент

## 2. Recoverable Omissions

> Every lossy omission is recoverable. No content is deleted without a traceable reference.

- Каждый удалённый блок заменяется адресуемым `[omitted: N lines, ref=artifact#Lx-Ly]`
- `expand(ref)` всегда возвращает оригинал
- Без ref удаление запрещено
- Ref не может указывать на несуществующий диапазон

## 3. Storage Cache ≠ Context Visibility

> Storage cache records what was compressed. Context ledger records what the model saw.

- Persistent cache НЕ является доказательством видимости моделью
- Ref выдаётся только если артефакт зарегистрирован в context ledger
- Новая сессия = чистый context ledger
- Evicted entry не считается visible

## 4. Session-Aware References

> References are scoped to session/conversation/agent. A ref valid in session A may be invalid in session B.

- Каждый ref проверяется против context ledger
- Cross-session refs запрещены по умолчанию
- Session boundary всегда сбрасывает visibility

## 5. Delta Requires Visible Base

> Delta encoding is only permitted when the base artifact is active in the context ledger.

- base_hash должен быть в context ledger
- base representation должен иметь статус `active`
- Verifier проверяет восстановление target hash
- При ошибке — fallback к полному target

## 6. Verification Failure → Raw Fallback

> When the verifier detects any violation, the system returns the raw, uncompressed output.

- Никаких partial/best-effort результатов
- Raw всегда доступен
- Fallback логируется с причиной
- Метрика `squeeze_fallback_raw_total` инкрементится

## 7. Unicode Safety

> Unicode input must never panic. Byte-index slicing without char boundary checks is forbidden.

- Все операции используют `.char_indices()` или эквивалент
- Property-based тесты для 1000+ Unicode cases
- Кириллица, CJK, Arabic, emoji, combining chars
- Malformed input не вызывает panic

## 8. Correctness > Token Savings

> Token savings never override correctness gates. A compression that breaks the agent's task is not an optimization.

- Hard gates в COS (Critical Field Recall ≥ 99.5%, Byte-Exact Recovery = 100%, Broken References = 0)
- Если агент теряет способность решать задачу — компрессия невалидна
- Source code critical omissions = 0
- Никакие token savings не оправдывают потерю идентификаторов, путей, ошибок

## 9. Provenance Preservation

> Two identical blobs in different paths produce different artifact records with distinct provenance.

- Артефакт хранит `source_path` всегда
- Content hash может указывать на общий blob
- Artifact record уникален для каждого source_path
- Provenance не теряется при dedup

## 10. Honest Benchmarking

> All benchmark claims must be reproducible and specify the tokenizer used.

- Каждая метрика: tokenizer_id, model_family, tokens_before/after
- Никаких "13 tokens" без указания tokenizer
- Raw vs Compressed agent task quality измеряется
- Все результаты воспроизводимы из репозитория
