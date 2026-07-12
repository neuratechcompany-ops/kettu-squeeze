"""Command-aware formatters — git, pytest, docker, kubectl, npm, curl, ls, find, grep, etc.

Each formatter: detect() → format() → verify(). Deterministic. No LLM.
"""
import re, json
from dataclasses import dataclass


@dataclass
class FormatResult:
    compressed: str; original_tokens: int; compressed_tokens: int
    command: str = ""; formatter: str = ""
    @property
    def ratio(self): return self.compressed_tokens / max(self.original_tokens, 1)
    @property
    def savings(self): return max(0, self.original_tokens - self.compressed_tokens)


# ═══════════════════════════════════════════════════════════════════════════════
# Git formatters
# ═══════════════════════════════════════════════════════════════════════════════
def git_status(output): 
    branch = re.search(r'On branch (\S+)', output)
    staged = len(re.findall(r'^\s*(modified|new file|deleted):', output, re.M))
    untracked = output.count("Untracked files:") > 0
    lines = [f"git: {branch.group(1) if branch else '?'}", f"staged:{staged}"]
    files = [l.strip() for l in output.split("\n") if l.strip().startswith(("modified:","deleted:","new file:","\t"))]
    if files: lines.extend(files[:20])
    return FormatResult(compressed="\n".join(lines), original_tokens=len(output)//3,
                        compressed_tokens=len("\n".join(lines))//3, command="git status", formatter="git_status")

def git_diff(output):
    files = re.findall(r'^diff --git a/(.+) b/(.+)', output, re.M)
    adds = output.count("\n+") - output.count("\n+++")
    dels = output.count("\n-") - output.count("\n---")
    changed = [l for l in output.split("\n") if l.startswith(("+","-")) and not l.startswith(("+++","---"))][:30]
    lines = [f"git diff: {len(files)} files, +{adds} -{dels}"] + changed
    return FormatResult(compressed="\n".join(lines), original_tokens=len(output)//3,
                        compressed_tokens=len("\n".join(lines))//3, command="git diff", formatter="git_diff")

def git_log(output): 
    commits = len(re.findall(r'^commit [a-f0-9]+', output, re.M))
    lines = [f"git log: {commits} commits"] + [l.strip() for l in output.split("\n") if l.strip().startswith(("    ","Author:","Date:"))][:20]
    return FormatResult(compressed="\n".join(lines), original_tokens=len(output)//3,
                        compressed_tokens=len("\n".join(lines))//3, command="git log", formatter="git_log")

# ═══════════════════════════════════════════════════════════════════════════════
# Test formatters
# ═══════════════════════════════════════════════════════════════════════════════
def pytest_format(output):
    passed = int(m.group(1)) if (m := re.search(r'(\d+) passed', output)) else 0
    failed = int(m.group(1)) if (m := re.search(r'(\d+) failed', output)) else 0
    exit_code = "FAIL" if failed > 0 else "OK"
    failures = [l for l in output.split("\n") if "FAIL" in l.upper() or "Error" in l or "assert" in l][:10]
    lines = [f"pytest {exit_code} {passed}P {failed}F"] + failures
    return FormatResult(compressed="\n".join(lines), original_tokens=len(output)//3,
                        compressed_tokens=len("\n".join(lines))//3, command="pytest", formatter="pytest")

# ═══════════════════════════════════════════════════════════════════════════════
# Container formatters
# ═══════════════════════════════════════════════════════════════════════════════
def docker_ps(output):
    containers = len([l for l in output.split("\n") if l.strip() and not l.startswith("CONTAINER")])
    lines = [f"docker: {containers} containers"] + [l for l in output.split("\n")[1:11] if l.strip()]
    return FormatResult(compressed="\n".join(lines), original_tokens=len(output)//3,
                        compressed_tokens=len("\n".join(lines))//3, command="docker ps", formatter="docker_ps")

def docker_images(output):
    images = len([l for l in output.split("\n") if l.strip() and not l.startswith("REPOSITORY")])
    lines = [f"docker: {images} images"] + [l for l in output.split("\n")[1:11] if l.strip()]
    return FormatResult(compressed="\n".join(lines), original_tokens=len(output)//3,
                        compressed_tokens=len("\n".join(lines))//3, command="docker images", formatter="docker_images")

def kubectl_get(output):
    items = len([l for l in output.split("\n") if l.strip() and not l.startswith("NAME")])
    lines = [f"kubectl: {items} items"] + [l for l in output.split("\n")[1:12] if l.strip()]
    return FormatResult(compressed="\n".join(lines), original_tokens=len(output)//3,
                        compressed_tokens=len("\n".join(lines))//3, command="kubectl get", formatter="kubectl_get")

# ═══════════════════════════════════════════════════════════════════════════════
# JS/TS formatters
# ═══════════════════════════════════════════════════════════════════════════════
def npm_install(output):
    added = len(re.findall(r'added (\d+) packages', output))
    lines = [f"npm: +{added} packages"] + [l for l in output.split("\n") if "added" in l or "removed" in l or "audited" in l][:5]
    return FormatResult(compressed="\n".join(lines), original_tokens=len(output)//3,
                        compressed_tokens=len("\n".join(lines))//3, command="npm install", formatter="npm_install")

# ═══════════════════════════════════════════════════════════════════════════════
# System formatters
# ═══════════════════════════════════════════════════════════════════════════════
def ls_format(output):
    items = len([l for l in output.split("\n") if l.strip()])
    lines = [f"ls: {items} items"] + [l for l in output.split("\n")[:20] if l.strip()]
    return FormatResult(compressed="\n".join(lines), original_tokens=len(output)//3,
                        compressed_tokens=len("\n".join(lines))//3, command="ls", formatter="ls")

def find_format(output):
    hits = len([l for l in output.split("\n") if l.strip()])
    lines = [f"find: {hits} matches"] + [l for l in output.split("\n")[:20] if l.strip()]
    return FormatResult(compressed="\n".join(lines), original_tokens=len(output)//3,
                        compressed_tokens=len("\n".join(lines))//3, command="find", formatter="find")

def grep_format(output):
    hits = len([l for l in output.split("\n") if l.strip()])
    lines = [f"grep: {hits} matches"] + [l for l in output.split("\n")[:20] if l.strip()]
    return FormatResult(compressed="\n".join(lines), original_tokens=len(output)//3,
                        compressed_tokens=len("\n".join(lines))//3, command="grep", formatter="grep")

def curl_format(output):
    status = re.search(r'HTTP/\d\.\d (\d+)', output)
    lines = [f"curl: HTTP {status.group(1) if status else '?'}", output[:200]]
    return FormatResult(compressed="\n".join(lines), original_tokens=len(output)//3,
                        compressed_tokens=len("\n".join(lines))//3, command="curl", formatter="curl")

# ═══════════════════════════════════════════════════════════════════════════════
# Detector + registry
# ═══════════════════════════════════════════════════════════════════════════════
FORMATTERS = {
    "git status": git_status, "git diff": git_diff, "git log": git_log,
    "pytest": pytest_format, "docker ps": docker_ps, "docker images": docker_images,
    "kubectl get": kubectl_get, "npm install": npm_install,
    "ls": ls_format, "find": find_format, "grep": grep_format, "curl": curl_format,
}

def detect_command(command: str, output: str) -> str | None:
    """Detect which formatter to use."""
    cmd_lower = command.lower().strip()
    for key in FORMATTERS:
        if all(w in cmd_lower for w in key.split()):
            return key
    # Heuristic detection from output
    if "PASSED" in output or "FAILED" in output:
        if "pytest" in cmd_lower or "test" in cmd_lower: return "pytest"
    if "CONTAINER ID" in output: return "docker ps"
    if "REPOSITORY" in output and "TAG" in output: return "docker images"
    if "NAME" in output and "READY" in output: return "kubectl get"
    return None

def format_output(command: str, output: str) -> FormatResult:
    """Apply best formatter for this command+output."""
    key = detect_command(command, output)
    if key and key in FORMATTERS:
        return FORMATTERS[key](output)
    return FormatResult(compressed=output, original_tokens=len(output)//3,
                        compressed_tokens=len(output)//3, command=command, formatter="passthrough")
