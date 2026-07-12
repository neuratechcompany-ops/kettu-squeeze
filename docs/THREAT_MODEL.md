# Kettu Squeeze — Threat Model

## Scope

Kettu Squeeze — локальный слой сжатия контекста между AI-агентом и tool outputs. Работает полностью локально, без сети.

## Assets

| Asset | Value | Impact of Loss |
|-------|-------|---------------|
| Raw tool output | High | Агент теряет информацию, неверные решения |
| Source code content | Critical | Неверный патч, security flaw, ложный аудит |
| Identifiers & symbols | Critical | Неверный refactor, битый импорт |
| Error messages & stack traces | High | Неверный диагноз, повтор ошибок |
| Artifact provenance | Medium | Путаница файлов, потеря контекста |
| Context ledger integrity | High | Cross-session leak, ложная видимость |
| Compression metadata | Low | Искажение статистики |
| Configuration | Medium | Изменение политик безопасности |

## Trust Boundaries

```text
┌─────────────────────────────────────────────┐
│                  Agent (LLM)                │
│  доверяет compressed output                 │
├─────────────────────────────────────────────┤
│              Trust Boundary                 │
├─────────────────────────────────────────────┤
│              Kettu Squeeze                  │
│  ┌───────────┐  ┌──────────┐  ┌──────────┐ │
│  │ Compressor│  │ Verifier │  │ Artifact │ │
│  │           │  │          │  │ Store    │ │
│  └───────────┘  └──────────┘  └──────────┘ │
├─────────────────────────────────────────────┤
│              Trust Boundary                 │
├─────────────────────────────────────────────┤
│          Tool / File / Command              │
│          полностью доверенный               │
└─────────────────────────────────────────────┘
```

Агент — untrusted с точки зрения системы (может пытаться эксплуатировать expand для утечки данных между сессиями), но trusted с точки зрения получателя output.

## Attack Vectors

### AV-1: Silent Content Removal

**Описание:** Компрессор удаляет критический контент без recoverable reference.

**Вектор:** entropy truncation, aggressive dedup, lossy mode без marking.

**Mitigation:**
- Verifier проверяет: все omitted блоки имеют refs
- Lossy mode маркируется `lossy=true` в ответе
- Source code по умолчанию STRICT_RAW
- Hard gate: Critical Field Recall ≥ 99.5%

### AV-2: Cross-Session Reference Leak

**Описание:** Агент в сессии B получает ref, указывающий на контент из сессии A, который текущая модель не видела.

**Вектор:** global persistent cache без scoping, context ledger bypass.

**Mitigation:**
- Context ledger: scoped по session_id + agent_id + conversation_id
- Ref проверяется: artifact_id в context ledger + status active
- Cross-session refs запрещены
- Hard gate: cross-session invalid refs = 0

### AV-3: Delta Without Visible Base

**Описание:** Delta отправляется агенту, но base artifact не находится в текущем context ledger.

**Вектор:** cache hit без проверки visibility, evicted base.

**Mitigation:**
- Delta требует: base_artifact_id в context ledger + active
- Verifier восстанавливает target hash
- Hard gate: Broken References = 0

### AV-4: Corrupted Recovery Chain

**Описание:** `expand(ref)` возвращает неверный или усечённый контент.

**Вектор:** битые line ranges, stale cache, race condition.

**Mitigation:**
- Atomic writes в artifact store
- Verifier проверяет: line ranges валидны, content hash совпадает
- Hard gate: Byte-Exact Recovery = 100%

### AV-5: Unicode Panic

**Описание:** Не-ASCII ввод вызывает panic в Rust-коде или UnicodeDecodeError в Python.

**Вектор:** byte-index slicing без проверки char boundaries, предположение ASCII.

**Mitigation:**
- Все операции character-boundary-aware
- Property-based тесты: 1000+ Unicode cases
- Hard gate: Unicode panic = 0

### AV-6: Prompt Injection via Tool Output

**Описание:** Tool output содержит строки, которые LLM интерпретирует как инструкции.

**Вектор:** `[SYSTEM: override previous instructions]`, fake refs, ложные error messages.

**Mitigation:**
- Не модифицировать семантику (lossless mode default)
- Не добавлять структуру, которая может быть misinterpreted
- Агент должен знать, что получает compressed representation

### AV-7: Provenance Confusion

**Описание:** Два файла с одинаковым содержимым сливаются в один artifact.

**Вектор:** content-hash dedup без сохранения source_path.

**Mitigation:**
- Общий blob для одинакового контента ок
- Но artifact records должны быть разными (разные source_path)
- Provenance сохраняется всегда

### AV-8: Silent Lossy Mode

**Описание:** Агент не знает, что получил lossy представление.

**Mitigation:**
- `lossy: true` в ответе API всегда
- Агент должен видеть предупреждение
- Lossy без запроса — только по explicit policy

### AV-9: Artifact Store Corruption

**Описание:** SQLite или blob storage повреждён.

**Mitigation:**
- SQLite WAL mode
- При ошибке чтения: fallback к raw tool output
- Не пытаться восстановить из битых данных

### AV-10: Hash Collision

**Описание:** SHA-256 коллизия (теоретически).

**Mitigation:**
- SHA-256 считается collision-resistant
- При обнаружении коллизии: fallback к raw
- Не хранить оба под одним ключом

## Risk Matrix

| Attack | Likelihood | Impact | Risk |
|--------|-----------|--------|------|
| AV-1: Silent Content Removal | Medium | Critical | Critical |
| AV-2: Cross-Session Leak | Medium | High | High |
| AV-3: Delta Without Base | Low | High | Medium |
| AV-4: Corrupted Recovery | Low | Critical | Medium |
| AV-5: Unicode Panic | High | Medium | High |
| AV-6: Prompt Injection | Medium | Medium | Medium |
| AV-7: Provenance Confusion | Medium | Medium | Medium |
| AV-8: Silent Lossy | Medium | High | High |
| AV-9: Storage Corruption | Low | High | Medium |
| AV-10: Hash Collision | Very Low | High | Low |
