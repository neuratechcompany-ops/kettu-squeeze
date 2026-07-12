"""
Agent Quality Benchmark Harness — Phase 3.

Three independent test suites:
1. Code Agent Benchmark — bug finding, refactoring, architecture Q&A
2. Tool Output Benchmark — pytest, docker logs, k8s, JSON, git diff
3. Long Session Benchmark — 200 sequential actions

Design:
- Scenarios store inputs and expected answer key points
- Deterministic metrics: tokens, refs, ratios, latency
- Agent quality requires LLM — flagged as 'needs_agent'
- NAB computed from available metrics
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from kettu_squeeze.api.engine import SqueezeEngine
from kettu_squeeze.types import (
    CompressionMode,
    CompressionRequest,
    SourceType,
)

from benchmarks.nab import NABComponents, compute_nab

# ═══════════════════════════════════════════════════════════════════════════════
# Scenario Definitions
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AgentAction:
    action_type: str
    description: str
    input_content: str | None = None
    source_path: str | None = None
    source_type: SourceType = SourceType.FILE
    expected_contains: list[str] = field(default_factory=list)

@dataclass
class ScenarioResult:
    scenario_name: str
    scenario_type: str
    total_actions: int
    raw_total_tokens: int = 0
    compressed_total_tokens: int = 0
    token_savings_pct: float = 0.0
    total_refs_created: int = 0
    expand_calls_needed: int = 0
    broken_refs: int = 0
    total_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    quality_degradation_pct: float = 0.0
    quality_measured: bool = False
    retry_count_delta: int = 0
    action_results: list[dict] = field(default_factory=list)
    nab: any = None

# ═══════════════════════════════════════════════════════════════════════════════
# Scenario Data (inline to avoid file I/O complexity)
# ═══════════════════════════════════════════════════════════════════════════════

def _read_scenario_data():
    """Return all scenario fixtures as (name, [actions]) tuples."""
    scenarios = []

    # ── CODE: Find bug in auth ──
    scenarios.append(("code_find_bug_auth", [
        AgentAction("read_file", "Read auth.py with bug",
            input_content=(
                '"""Authentication with a subtle bug."""\n'
                'import hashlib\n\n'
                'def verify_password(password, stored_hash, salt):\n'
                '    """BUG: does not use salt in verification."""\n'
                '    computed = hashlib.sha256(password.encode()).hexdigest()\n'
                '    return computed == stored_hash\n\n'
                'def login(username, password):\n'
                '    stored = "abc123"\n'
                '    # Salt is passed but ignored in verify_password!\n'
                '    return verify_password(password, stored, salt="randomsalt")\n'
            ),
            source_path="/src/auth.py",
            expected_contains=["verify_password", "hashlib.sha256", "salt"],
        ),
        AgentAction("reason", "Agent finds: verify_password ignores salt parameter",
            expected_contains=["salt", "ignored", "hashlib.sha256(password.encode())"],
        ),
    ]))

    # ── CODE: Refactor worker pool ──
    scenarios.append(("code_refactor_worker", [
        AgentAction("read_file", "Read worker.py",
            input_content=(
                '"""Worker pool with retry — needs refactoring."""\n'
                'import time\nfrom threading import Thread\nfrom queue import Queue\n\n'
                'class Worker:\n'
                '    def __init__(self):\n'
                '        self.tasks = Queue()\n'
                '        self.running = False\n'
                '    def start(self):\n'
                '        self.running = True\n'
                '        for _ in range(4):\n'
                '            t = Thread(target=self._loop)\n'
                '            t.daemon = True\n'
                '            t.start()\n'
                '    def _loop(self):\n'
                '        while self.running:\n'
                '            try:\n'
                '                task = self.tasks.get(timeout=1)\n'
                '                result = task()\n'
                '                print(f"Task done: {result}")\n'
                '            except Exception as e:\n'
                '                print(f"Task failed: {e}")\n'
                '    def submit(self, task):\n'
                '        self.tasks.put(task)\n'
                '    def stop(self):\n'
                '        self.running = False\n'
            ),
            source_path="/src/worker.py",
            expected_contains=["Worker", "Queue", "Thread", "submit"],
        ),
        AgentAction("reason", "Agent identifies: no retry logic, no error handling, no max_retries",
            expected_contains=["retry", "backoff", "max_retries", "logging"],
        ),
    ]))

    # ── CODE: Architecture question ──
    scenarios.append(("code_architecture_question", [
        AgentAction("read_file", "Read middleware.py",
            input_content=(
                '"""Middleware pipeline."""\n'
                'from typing import Callable\n\n'
                'class Pipeline:\n'
                '    def __init__(self):\n'
                '        self._middlewares = []\n'
                '    def use(self, middleware):\n'
                '        self._middlewares.append(middleware)\n'
                '    async def execute(self, request):\n'
                '        response = request\n'
                '        for mw in self._middlewares:\n'
                '            response = await mw(response)\n'
                '            if response.get("_abort"):\n'
                '                break\n'
                '        return response\n\n'
                'class AuthMiddleware:\n'
                '    def __init__(self, secret):\n'
                '        self.secret = secret\n'
                '    async def __call__(self, request):\n'
                '        token = request.get("headers", {}).get("authorization")\n'
                '        if not token or token != f"Bearer {self.secret}":\n'
                '            return {"_abort": True, "error": "Unauthorized"}\n'
                '        return request\n\n'
                'class RateLimitMiddleware:\n'
                '    def __init__(self, max_rps=100):\n'
                '        self.max_rps = max_rps\n'
                '        self._counters = {}\n'
                '    async def __call__(self, request):\n'
                '        client_ip = request.get("client_ip", "unknown")\n'
                '        self._counters[client_ip] = self._counters.get(client_ip, 0) + 1\n'
                '        if self._counters[client_ip] > self.max_rps:\n'
                '            return {"_abort": True, "error": "Rate limited"}\n'
                '        return request\n'
            ),
            source_path="/src/middleware.py",
            expected_contains=["Pipeline", "AuthMiddleware", "RateLimitMiddleware"],
        ),
        AgentAction("reason", "Agent answers: Chain of Responsibility pattern, rate limit bug, memory leak",
            expected_contains=["Chain of Responsibility", "memory leak", "rate per second"],
        ),
    ]))

    # ── CODE: Write tests for parser ──
    scenarios.append(("code_write_test", [
        AgentAction("read_file", "Read parser.py with eval()",
            input_content=(
                '"""Simple expression evaluator."""\n'
                'def evaluate(expr):\n'
                '    """Supports +, -, *, /. Uses eval — unsafe."""\n'
                '    expr = expr.replace(" ", "")\n'
                '    if "/0" in expr.replace(".", ""):\n'
                '        raise ZeroDivisionError("Division by zero")\n'
                '    return float(eval(expr, {"__builtins__": {}}, {}))\n\n'
                'def tokenize(expr):\n'
                '    tokens = []\n'
                '    current = ""\n'
                '    for ch in expr:\n'
                '        if ch in "+-*/()":\n'
                '            if current:\n'
                '                tokens.append(current)\n'
                '                current = ""\n'
                '            tokens.append(ch)\n'
                '        else:\n'
                '            current += ch\n'
                '    if current:\n'
                '        tokens.append(current)\n'
                '    return tokens\n'
            ),
            source_path="/src/parser.py",
            expected_contains=["evaluate", "tokenize", "eval", "ZeroDivisionError"],
        ),
        AgentAction("reason", "Agent writes tests and notes eval() safety issue",
            expected_contains=["eval", "unsafe", "test_divide_by_zero", "ast.literal_eval"],
        ),
    ]))

    # ── CODE: Security audit ──
    scenarios.append(("code_security_audit", [
        AgentAction("read_file", "Read db.py with SQL injection and MD5",
            input_content=(
                '"""User service with security issues."""\n'
                'import sqlite3, hashlib\n'
                'DB = sqlite3.connect(":memory:")\n\n'
                'def get_user(user_id):\n'
                '    """VULNERABLE to SQL injection."""\n'
                '    query = f"SELECT * FROM users WHERE id = {user_id}"\n'
                '    cursor = DB.execute(query)\n'
                '    row = cursor.fetchone()\n'
                '    if row:\n'
                '        return {"id": row[0], "name": row[1], "role": row[2]}\n'
                '    return None\n\n'
                'def create_user(name, password, role="user"):\n'
                '    """Password stored as MD5 — weak hash."""\n'
                '    pw_hash = hashlib.md5(password.encode()).hexdigest()\n'
                '    query = f"INSERT INTO users (name, password, role) '
                'VALUES (\'{name}\', \'{pw_hash}\', \'{role}\')"\n'
                '    cursor = DB.execute(query)\n'
                '    DB.commit()\n'
                '    return cursor.lastrowid\n'
            ),
            source_path="/src/db.py",
            expected_contains=["get_user", "create_user", "sqlite3", "md5"],
        ),
        AgentAction("reason", "Agent finds: SQL injection, MD5, no input validation, privilege escalation",
            expected_contains=["SQL injection", "MD5", "bcrypt", "input validation", "privilege"],
        ),
    ]))

    # ── TOOL: Pytest mixed ──
    pytest_out = (
        '============================= test session starts ==============================\n'
        'collected 45 items\n\n'
        'test_auth.py::test_hash_password PASSED\n'
        'test_auth.py::test_verify_password PASSED\n'
        'test_auth.py::test_login FAILED\n'
        'test_worker.py::test_submit PASSED\n'
        'test_worker.py::test_retry PASSED\n'
        'test_parser.py::test_evaluate_add PASSED\n'
        'test_parser.py::test_evaluate_div PASSED\n'
        'test_parser.py::test_evaluate_div_by_zero FAILED\n'
        'test_parser.py::test_tokenize PASSED\n'
        'test_db.py::test_get_user PASSED\n'
        'test_db.py::test_create_user FAILED\n'
        'test_db.py::test_sql_injection PASSED\n'
        '35 passed, 3 failed, 7 skipped in 12.34s\n\n'
        'FAILURES:\n'
        '  test_auth.py::test_login - AssertionError: Expected True, got False\n'
        '  test_parser.py::test_evaluate_div_by_zero - ZeroDivisionError not raised\n'
        '  test_db.py::test_create_user - sqlite3.OperationalError: no such column: email\n'
    )
    scenarios.append(("tool_pytest_mixed", [
        AgentAction("run_command", "Run pytest suite", pytest_out, "pytest", SourceType.TOOL,
            expected_contains=["35 passed", "3 failed", "test_login", "ZeroDivisionError"]),
        AgentAction("reason", "Agent identifies 3 failures and their causes",
            expected_contains=["test_login", "ZeroDivisionError", "email column"]),
    ]))

    # ── TOOL: Docker crash loop ──
    docker_out = (
        'web_1  | [INFO] Starting application v2.3.1\n'
        'web_1  | [INFO] Connecting to database at postgresql://db:5432/app\n'
        'web_1  | [ERROR] Connection refused. Retrying in 5s...\n'
        'web_1  | [ERROR] Connection refused. Retrying in 5s...\n'
        'web_1  | [ERROR] Connection refused. Retrying in 5s...\n'
        'web_1  | [ERROR] Connection refused. Retrying in 5s...\n'
        'web_1  | [ERROR] Connection refused. Retrying in 5s...\n'
        'web_1  | [FATAL] Max retries exceeded. Exiting.\n'
        'web_1  | [INFO] Starting application v2.3.1\n'
        'web_1  | [ERROR] Connection refused. Retrying in 5s...\n'
        'web_1  | [ERROR] Connection refused. Retrying in 5s...\n'
        'web_1  | [FATAL] Max retries exceeded. Exiting.\n'
        'db_1   | [INFO] PostgreSQL 16.3 starting\n'
        'db_1   | [ERROR] could not open directory /var/lib/postgresql/data: Permission denied\n'
        'db_1   | [FATAL] Database startup failed\n'
    )
    scenarios.append(("tool_docker_crash_loop", [
        AgentAction("run_command", "docker-compose logs", docker_out, "docker", SourceType.TOOL,
            expected_contains=["Connection refused", "Permission denied", "FATAL"]),
        AgentAction("reason", "Root cause: volume permissions on postgres data dir",
            expected_contains=["Permission denied", "volume", "chown", "postgres"]),
    ]))

    # ── TOOL: Large JSON ──
    large_json = json.dumps({
        "status": "ok", "data": {
            "users": [
                {"id": i, "name": f"User_{i}", "email": f"user{i}@example.com",
                 "role": "admin" if i < 3 else "user", "active": i % 3 != 0}
                for i in range(50)
            ], "total": 50, "page": 1
        }
    })
    scenarios.append(("tool_large_json", [
        AgentAction("run_command", "curl GET /api/users", large_json, "api.json", SourceType.API,
            expected_contains=["total", "50", "admin"]),
        AgentAction("reason", "Answers: 50 users, 3 admins, structure analysis",
            expected_contains=["3 admins", "admin"]),
    ]))

    # ── TOOL: Git diff ──
    diff_out = (
        'diff --git a/src/auth.py b/src/auth.py\n'
        '--- a/src/auth.py\n+++ b/src/auth.py\n'
        '@@ -45,7 +45,7 @@ class AuthService:\n'
        '-        user = self._users.get(username)\n'
        '+        user = self.db.find_user(username)\n'
        '@@ -60,3 +60,10 @@ class AuthService:\n'
        '+    def refresh_token(self, token):\n'
        '+        payload = jwt.decode(token, self.token_secret, algorithms=["HS256"])\n'
        '+        if payload.get("exp", 0) < time.time():\n'
        '+            raise TokenExpiredError("Token expired")\n'
        '+        payload["exp"] = time.time() + 3600\n'
        '+        return jwt.encode(payload, self.token_secret, algorithm="HS256")\n'
        'diff --git a/src/db.py b/src/db.py\n'
        '--- a/src/db.py\n+++ b/src/db.py\n'
        '@@ -12,6 +12,9 @@ class Database:\n'
        '-            "SELECT * FROM users WHERE username = ?", (username,)\n'
        '+            "SELECT id, username, password_hash, salt, role FROM users WHERE username = ?",\n'
        '+            (username,)\n'
    )
    scenarios.append(("tool_git_diff_analysis", [
        AgentAction("run_command", "git diff main..feature/auth-refresh", diff_out, "git_diff", SourceType.TOOL,
            expected_contains=["auth.py", "db.py", "refresh_token", "find_user"]),
        AgentAction("reason", "Agent analyzes: db.find_user migration, new refresh_token, missing rate limit",
            expected_contains=["db.find_user", "_users", "refresh_token", "rate limiting"]),
    ]))

    # ── TOOL: K8s crash ──
    k8s_out = (
        'NAME                     READY   STATUS             RESTARTS   AGE\n'
        'api-gateway-7d8f9c-abc12   1/1     Running            0          5m\n'
        'auth-service-5e3a1b-def34  0/1     CrashLoopBackOff   12         30m\n'
        'user-service-9f2c4d-ghi56  1/1     Running            2          30m\n'
        'payments-3a7b8c-jkl78      0/1     Error              8          25m\n\n'
        'Events:\n'
        '  Warning  BackOff     pod/auth-service  Back-off restarting failed container\n'
        '  Warning  Unhealthy   pod/payments      Readiness probe failed: '
        'dial tcp 10.0.1.5:8080: connect: connection refused\n'
        '  Warning  Unhealthy   pod/payments      Liveness probe failed: '
        'HTTP probe failed with statuscode: 500\n'
    )
    scenarios.append(("tool_k8s_crash", [
        AgentAction("run_command", "kubectl get pods + describe", k8s_out, "kubectl", SourceType.TOOL,
            expected_contains=["CrashLoopBackOff", "Error", "Readiness probe", "500"]),
        AgentAction("reason", "Agent identifies: auth CrashLoopBackOff (12 restarts), payments returning 500",
            expected_contains=["CrashLoopBackOff", "12 restarts", "500", "logs"]),
    ]))

    # ── LONG SESSION: 200 actions ──
    long_actions = []
    for i in range(200):
        phase = i // 50
        if phase == 0:  # Exploration
            if i % 3 == 0:
                long_actions.append(AgentAction(
                    "read_file", f"Read module_{i%10}.py",
                    f"def func_{i}(x, y):\n    return x + y + {i}\n",
                    f"/src/module_{i%10}.py"))
            elif i % 3 == 1:
                long_actions.append(AgentAction(
                    "run_command", f"grep pattern_{i%5}",
                    f"src/module_{i%3}.py:42: def func_{i}(): pass\n",
                    "grep", SourceType.TOOL))
            else:
                status = "PASSED" if i % 5 != 0 else "FAILED"
                long_actions.append(AgentAction(
                    "run_command", "pytest",
                    f"test_feature_{i%20} {status}\n{20-i%5} passed, {i%5} failed\n",
                    "pytest", SourceType.TOOL))
        elif phase == 1:  # Debug — repeated reads
            long_actions.append(AgentAction(
                "read_file", f"Re-read buggy_{i%3}.py",
                f"def buggy_func_{i%3}(data):\n    # BUG at line {i+10}\n    return data[{i%5}:]\n",
                f"/src/buggy_{i%3}.py"))
        elif phase == 2:  # Fix — test runs
            if i % 2 == 0:
                long_actions.append(AgentAction(
                    "run_command", f"pytest test_feature_{i%20}",
                    f"test_feature_{i%20} PASSED\n1 passed\n",
                    "pytest", SourceType.TOOL))
            else:
                long_actions.append(AgentAction(
                    "read_file", f"Verify fix in fixed_{i%5}.py",
                    f"def fixed_func_{i%5}(x):\n    return x * 2  # fixed\n",
                    f"/src/fixed_{i%5}.py"))
        else:  # Phase 3 — Review
            choice = i % 4
            if choice == 0:
                long_actions.append(AgentAction(
                    "read_file", f"Review review_{i%7}.py",
                    f"def review_func_{i%7}(config):\n    return config.get('key', 'default')\n",
                    f"/src/review_{i%7}.py"))
            elif choice == 1:
                long_actions.append(AgentAction(
                    "run_command", "git diff --stat",
                    f" src/module_{i%5}.py | 2 +-\n",
                    "git_diff", SourceType.TOOL))
            elif choice == 2:
                long_actions.append(AgentAction(
                    "expand_ref", "Expand omitted log lines",
                    f"[INFO] Background task {i} completed\n",
                    None, SourceType.TOOL))
            else:
                long_actions.append(AgentAction(
                    "run_command", "docker ps",
                    "CONTAINER ID   IMAGE          STATUS\nabc123   app:v2.3.1    Up 2h\n",
                    "docker", SourceType.TOOL))

    scenarios.append(("long_session_200", long_actions))

    return scenarios


# ═══════════════════════════════════════════════════════════════════════════════
# Benchmark Runner
# ═══════════════════════════════════════════════════════════════════════════════

class BenchmarkRunner:
    def __init__(self):
        self.engine = SqueezeEngine()

    def run_scenario(self, scenario_name, scenario_type, actions, session_id=None):
        if session_id is None:
            session_id = f"bench-{scenario_name}-{uuid.uuid4().hex[:8]}"

        result = ScenarioResult(scenario_name=scenario_name, scenario_type=scenario_type,
                                total_actions=len(actions))
        raw_tokens = 0
        compressed_tokens = 0
        total_refs = 0
        total_latency = 0.0
        expand_calls = 0

        for i, action in enumerate(actions):
            if action.input_content is None:
                continue
            content = action.input_content
            raw_tokens += self._estimate_tokens(content)

            start = time.perf_counter()
            resp = self.engine.compress(CompressionRequest(
                content=content, source_type=action.source_type,
                source_path=action.source_path, session_id=session_id,
                agent_id="bench-agent", mode=CompressionMode.LOSSLESS))
            elapsed = time.perf_counter() - start
            total_latency += elapsed

            compressed_tokens += resp.compressed_tokens
            total_refs += len(resp.refs)
            if resp.refs:
                expand_calls += len(resp.refs)

            critical_ok = all(
                expected in resp.content or expected in " ".join(resp.refs)
                for expected in action.expected_contains
            )
            result.action_results.append({
                "step": i, "action_type": action.action_type,
                "raw_tokens": self._estimate_tokens(content),
                "compressed_tokens": resp.compressed_tokens,
                "compression_ratio": resp.compression_ratio,
                "refs": len(resp.refs), "critical_ok": critical_ok,
            })

        result.raw_total_tokens = raw_tokens
        result.compressed_total_tokens = compressed_tokens
        result.token_savings_pct = (raw_tokens - compressed_tokens) / max(raw_tokens, 1) * 100
        result.total_refs_created = total_refs
        result.expand_calls_needed = expand_calls
        result.total_latency_ms = total_latency * 1000
        result.avg_latency_ms = (total_latency / max(len(actions), 1)) * 1000
        result.quality_measured = False

        nab_components = NABComponents(
            token_savings_pct=round(result.token_savings_pct, 1),
            memory_reduction_pct=round(result.token_savings_pct, 1),
            extra_expand_calls=expand_calls,
            scenario=scenario_name, total_actions=len(actions),
            raw_total_tokens=raw_tokens, compressed_total_tokens=compressed_tokens,
            quality_measured=False)
        result.nab = compute_nab(nab_components)
        return result

    def run_all(self):
        results = {"code_agent": [], "tool_output": [], "long_session": []}
        for name, actions in _read_scenario_data():
            if name.startswith("code_"):
                results["code_agent"].append(self.run_scenario(name, "code", actions))
            elif name.startswith("tool_"):
                results["tool_output"].append(self.run_scenario(name, "tool_output", actions))
            else:
                results["long_session"].append(self.run_scenario(name, "long_session", actions))
        return results

    @staticmethod
    def _estimate_tokens(text):
        try:
            import tiktoken
            return len(tiktoken.get_encoding("cl100k_base").encode(text))
        except ImportError:
            return len(text) // 3


# ═══════════════════════════════════════════════════════════════════════════════
# Report Generator
# ═══════════════════════════════════════════════════════════════════════════════

def generate_report(results):
    lines = [
        "═══════════════════════════════════════════════════",
        "  Kettu Squeeze — Agent Quality Benchmark Report",
        "  Phase 3: Proof of Effectiveness",
        "═══════════════════════════════════════════════════", "",
    ]
    all_results = [r for g in results.values() for r in g]
    total_raw = sum(r.raw_total_tokens for r in all_results)
    total_comp = sum(r.compressed_total_tokens for r in all_results)
    total_actions = sum(r.total_actions for r in all_results)
    total_refs = sum(r.total_refs_created for r in all_results)
    total_expands = sum(r.expand_calls_needed for r in all_results)
    avg_savings = sum(r.token_savings_pct for r in all_results) / max(len(all_results), 1)

    lines.append("── Aggregate Metrics ──")
    lines.append(f"  Scenarios:      {len(all_results)}")
    lines.append(f"  Total actions:  {total_actions}")
    lines.append(f"  Raw tokens:     {total_raw:,}")
    lines.append(f"  Compressed:     {total_comp:,}")
    lines.append(f"  Savings:        {total_raw - total_comp:,} tokens ({avg_savings:.1f}% avg)")
    lines.append(f"  Refs created:   {total_refs}")
    lines.append(f"  Expand calls:   {total_expands}")
    lines.append("")

    for group_name, group_results in results.items():
        lines.append(f"── {group_name.upper()} ({len(group_results)} scenarios) ──")
        for r in group_results:
            nab_status = r.nab.status.value if r.nab else "N/A"
            quality_note = " [needs LLM agent]" if not r.quality_measured else ""
            lines.append(
                f"  {r.scenario_name:35s}  "
                f"tokens: {r.raw_total_tokens:>5,}→{r.compressed_total_tokens:>5,}  "
                f"({r.token_savings_pct:>5.1f}%)  "
                f"refs: {r.total_refs_created:>3}  "
                f"NAB: {r.nab.score:+.3f} [{nab_status}]{quality_note}")
        group_nab = sum(r.nab.score for r in group_results) / max(len(group_results), 1)
        group_sav = sum(r.token_savings_pct for r in group_results) / max(len(group_results), 1)
        g_raw = sum(r.raw_total_tokens for r in group_results)
        g_comp = sum(r.compressed_total_tokens for r in group_results)
        lines.append(
            f"  {'GROUP AVG':35s}  "
            f"tokens: {g_raw:>5,}→{g_comp:>5,}  "
            f"({group_sav:>5.1f}%)  NAB: {group_nab:+.3f}")
        lines.append("")

    lines.append("── Net Agent Benefit Summary ──")
    overall_nab = sum(r.nab.score for r in all_results) / max(len(all_results), 1)
    if overall_nab > 0.1:
        verdict = "BENEFICIAL — compression provides net positive value"
    elif overall_nab < -0.1:
        verdict = "DETRIMENTAL — compression hurts more than it helps"
    else:
        verdict = "NEUTRAL — no significant net effect"
    lines.append(f"  Overall NAB: {overall_nab:+.4f}")
    lines.append(f"  Verdict:     {verdict}")

    if not any(r.quality_measured for r in all_results):
        lines.extend(["",
            "  ⚠  Agent quality NOT measured — no LLM agent available.",
            "     NAB reflects token savings only (quality degradation assumed 0%).",
            "     To complete: run these scenarios with an actual LLM agent",
            "     and measure task success rate, error count, and time to solution."])

    lines.extend(["", "── Recommendations ──"])
    best = max(all_results, key=lambda r: r.token_savings_pct)
    worst = min(all_results, key=lambda r: r.token_savings_pct)
    lines.append(f"  Best compression:  {best.scenario_name} ({best.token_savings_pct:.1f}%)")
    lines.append(f"  Worst compression: {worst.scenario_name} ({worst.token_savings_pct:.1f}%)")
    avg_lat = sum(r.avg_latency_ms for r in all_results) / max(len(all_results), 1)
    lines.append(f"  Avg latency/action: {avg_lat:.2f}ms")
    return "\n".join(lines)


if __name__ == "__main__":
    runner = BenchmarkRunner()
    results = runner.run_all()
    print(generate_report(results))
