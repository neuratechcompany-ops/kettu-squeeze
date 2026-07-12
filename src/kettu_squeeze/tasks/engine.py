"""Task-Aware Compression — v0.5 core.

Task Detector: 12 task types, rule-based, no LLM.
Task Planner: keep/drop rules per task.
Context budget allocation per task type.
"""

import re
from dataclasses import dataclass, field
from enum import Enum


class TaskType(str, Enum):
    DEBUG = "debug"
    TEST_FIX = "test_fix"
    CODE_REVIEW = "code_review"
    ARCHITECTURE = "architecture"
    SEARCH = "search"
    ROOT_CAUSE = "root_cause"
    CONFIG_EDIT = "config_edit"
    LOG_ANALYSIS = "log_analysis"
    JSON_API = "json_api"
    DOCKER = "docker"
    KUBERNETES = "kubernetes"
    GIT = "git"
    GENERIC = "generic"


@dataclass
class TaskDetection:
    task: TaskType = TaskType.GENERIC
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)


# ── Detection rules ──
DETECTION_RULES = {
    TaskType.DEBUG: [
        (r"(?i)(debug|traceback|exception|error|bug|fix|crash)", 0.8),
        (r"Traceback \(most recent call last\)", 0.95),
        (r"(?i)(what('s| is) wrong|why.*(fail|error|crash))", 0.85),
    ],
    TaskType.TEST_FIX: [
        (r"(?i)(pytest|FAILED|test.*fail|assert|unittest)", 0.8),
        (r"\d+ passed.*\d+ failed", 0.9),
        (r"(?i)(fix.*test|repair.*test|make.*test.*pass)", 0.85),
    ],
    TaskType.DOCKER: [
        (r"(?i)(docker|container|image)", 0.8),
        (r"CONTAINER ID", 0.9),
        (r"(?i)(Exited|Restarting|OOMKilled)", 0.85),
    ],
    TaskType.KUBERNETES: [
        (r"(?i)(kubectl|kubernetes|k8s|pod|deploy)", 0.8),
        (r"(CrashLoopBackOff|ImagePullBackOff|OOMKilled|Evicted)", 0.9),
    ],
    TaskType.GIT: [
        (r"(?i)(git |commit|branch|merge|rebase|diff)", 0.75),
        (r"(diff --git|--- a/|\+\+\+ b/)", 0.9),
        (r"(?i)(what.*changed|show.*diff|files.*modified)", 0.8),
    ],
    TaskType.JSON_API: [
        (r'^\s*[{\[]', 0.6),
        (r"(?i)(api|endpoint|response|json|status.*code)", 0.75),
        (r'"status":\s*"(error|ok)"', 0.85),
    ],
    TaskType.LOG_ANALYSIS: [
        (r"(?i)(log|stdout|stderr|journal)", 0.7),
        (r"(\[ERROR\]|\[WARN\]|\[INFO\]|FATAL)", 0.8),
        (r"(?i)(what happened|check.*log|examine.*log)", 0.75),
    ],
    TaskType.ROOT_CAUSE: [
        (r"(?i)(root cause|why|reason|source of|what caused|what is the cause)", 0.7),
        (r"(?i)(investigate|dig into|trace back|what went wrong)", 0.7),
        (r"(?i)(outage|incident|failure|cascading)", 0.75),
    ],
    TaskType.CODE_REVIEW: [
        (r"(?i)(review|audit|check.*code|inspect)", 0.6),
        (r"(?i)(security|vulnerability|CVE|injection|leak)", 0.85),
        (r"(def |class |import |function)", 0.5),
    ],
    TaskType.ARCHITECTURE: [
        (r"(?i)(architecture|design|structure|component|module|layer)", 0.7),
        (r"(?i)(how.*organized|overall.*structure|system.*design)", 0.75),
    ],
    TaskType.CONFIG_EDIT: [
        (r"(?i)(config|setting|yaml|toml|ini|env)", 0.7),
        (r"(?i)(change.*config|update.*setting|modify.*param)", 0.8),
    ],
    TaskType.SEARCH: [
        (r"(?i)(find|search|locate|where is|look for)", 0.6),
        (r"(?i)(grep|rg|find.*file)", 0.8),
    ],
}


def detect_task(prompt: str, tool_outputs: list[str] = None) -> TaskDetection:
    """Detect the agent's current task from prompt and tool context."""
    combined = prompt
    if tool_outputs:
        combined += "\n" + "\n".join(tool_outputs[-5:])  # last 5 outputs

    best_task = TaskType.GENERIC
    best_confidence = 0.0
    reasons = []
    matched = []

    for task, rules in DETECTION_RULES.items():
        task_conf = 0.0
        task_matches = 0
        for pattern, weight in rules:
            if re.search(pattern, combined):
                task_conf = max(task_conf, weight)
                task_matches += 1
        if task_matches >= 2 or task_conf >= 0.85:
            if task_conf > best_confidence:
                best_task = task
                best_confidence = task_conf
                reasons.append(f"{task.value}: {task_matches} rules matched (top={task_conf:.0%})")
                matched.append(task.value)

    if best_confidence < 0.5:
        return TaskDetection(task=TaskType.GENERIC, confidence=0.3,
                            reasons=["no strong signal — using generic"])

    return TaskDetection(task=best_task, confidence=best_confidence,
                         reasons=reasons[-3:], matched_rules=matched[-5:])


# ── Task Planner: keep/drop per task type ──
KEEP_PATTERNS = {
    TaskType.DEBUG: [r"Traceback", r"Error", r"Exception", r"File \"", r"line \d+", r"raise "],
    TaskType.TEST_FIX: [r"FAILED", r"assert", r"Error", r"test_", r"line \d+", r"got:", r"expected:"],
    TaskType.DOCKER: [r"Exited", r"Error", r"Restarting", r"OOMKilled", r"CONTAINER", r"port"],
    TaskType.KUBERNETES: [r"CrashLoop", r"Error", r"OOMKilled", r"Failed", r"ImagePull", r"Probe"],
    TaskType.GIT: [r"diff --git", r"\+\+\+", r"---", r"\+", r"^-", r"modified:", r"deleted:"],
    TaskType.JSON_API: [r'"status"', r'"error"', r'"message"', r'"code"', r'"id"', r'"count"'],
    TaskType.LOG_ANALYSIS: [r"ERROR", r"FATAL", r"CRITICAL", r"WARN", r"Exception", r"timeout"],
    TaskType.ROOT_CAUSE: [r"Error", r"Exception", r"caused by", r"Traceback", r"last", r"first"],
    TaskType.CODE_REVIEW: [r"def ", r"class ", r"TODO", r"FIXME", r"import ", r"security", r"CVE"],
    TaskType.ARCHITECTURE: [r"class ", r"def ", r"import ", r"component", r"module", r"layer"],
    TaskType.CONFIG_EDIT: [r"=", r":", r"host", r"port", r"password", r"secret", r"token"],
    TaskType.SEARCH: [r"TODO", r"FIXME", r"HACK", r"match", r"found"],
    TaskType.GENERIC: [r"Error", r"WARN", r"TODO", r"FIXME"],
}

DROP_PATTERNS = {
    TaskType.DEBUG: [r"^INFO", r"^DEBUG", r"heartbeat", r"startup complete", r"pip install"],
    TaskType.TEST_FIX: [r"PASSED", r"plugins", r"warnings summary", r"coverage:", r"=+$"],
    TaskType.DOCKER: [r"Up \d+", r"healthy", r"^INFO", r"startup"],
    TaskType.KUBERNETES: [r"Running", r"1/1", r"healthy", r"^INFO"],
    TaskType.GIT: [r"^index ", r"^ mode ", r"^@@.*@@$"],
    TaskType.JSON_API: [r'"debug"', r'"trace"', r'"stack_raw"', r'"_internal"'],
    TaskType.LOG_ANALYSIS: [r"^INFO", r"^DEBUG", r"heartbeat", r"gc completed"],
    TaskType.ROOT_CAUSE: [r"^INFO", r"^DEBUG", r"heartbeat"],
    TaskType.GENERIC: [r"heartbeat", r"^\s*$"],
}


def plan_content(task: TaskType, content: str, budget_tokens: int = 8000) -> str:
    """Apply task-aware keep/drop to content."""
    keep = KEEP_PATTERNS.get(task, KEEP_PATTERNS[TaskType.GENERIC])
    drop = DROP_PATTERNS.get(task, DROP_PATTERNS[TaskType.GENERIC])

    lines = content.split("\n")
    result = []
    kept = 0
    dropped = 0

    for line in lines:
        should_keep = any(re.search(p, line) for p in keep)
        should_drop = any(re.search(p, line) for p in drop) and not should_keep

        if should_keep or not should_drop:
            result.append(line)
            kept += 1
        else:
            dropped += 1
            if dropped <= 3:
                result.append(f"[{dropped} similar lines collapsed]")

    planned = "\n".join(result)
    return planned


def compress_task_aware(prompt: str, content: str, tool_outputs: list[str] = None,
                        budget_tokens: int = 8000) -> str:
    """Full task-aware compression pipeline."""
    detection = detect_task(prompt, tool_outputs)
    planned = plan_content(detection.task, content, budget_tokens)
    return planned
