"""Command-aware formatters — 20 commands. Deterministic. No LLM."""
import re
from dataclasses import dataclass

@dataclass
class FormatResult:
    compressed: str; original_tokens: int; compressed_tokens: int
    command: str = ""; formatter: str = ""
    @property
    def ratio(self): return self.compressed_tokens / max(self.original_tokens, 1)
    @property
    def savings(self): return max(0, self.original_tokens - self.compressed_tokens)

def _tok(t): return len(t)//3

# Git
def git_status(o): 
    b = re.search(r'On branch (\S+)', o); s = len(re.findall(r'^\s*(modified|new file|deleted):', o, re.M))
    lns = [f"git: {b.group(1) if b else '?'}", f"staged:{s}"] + [l.strip() for l in o.split("\n") if l.strip().startswith(("modified:","deleted:","new file:","\t"))][:20]
    return FormatResult("\n".join(lns), _tok(o), _tok("\n".join(lns)), "git status", "git_status")

def git_diff(o):
    fs = re.findall(r'^diff --git a/(.+) b/(.+)', o, re.M); a = o.count("\n+")-o.count("\n+++"); d = o.count("\n-")-o.count("\n---")
    ch = [l for l in o.split("\n") if l.startswith(("+","-")) and not l.startswith(("+++","---"))][:30]
    return FormatResult("\n".join([f"git diff: {len(fs)} files, +{a} -{d}"]+ch), _tok(o), _tok("\n".join([f"git diff: {len(fs)} files, +{a} -{d}"]+ch)), "git diff", "git_diff")

def git_log(o):
    c = len(re.findall(r'^commit [a-f0-9]+', o, re.M))
    return FormatResult("\n".join([f"git log: {c} commits"]+[l for l in o.split("\n") if l.startswith(("    ","Author:","Date:"))][:20]), _tok(o), _tok("\n".join([f"git log: {c} commits"])), "git log", "git_log")

def git_show(o):
    cm = re.search(r'commit ([a-f0-9]+)', o); au = re.search(r'Author: (.+)', o); dt = re.search(r'Date:\s+(.+)', o)
    lns = [f"git show: {cm.group(1)[:8] if cm else '?'}"]
    if au: lns.append(f"Author: {au.group(1)}")
    if dt: lns.append(f"Date: {dt.group(1)}")
    di = o.find("diff --git"); 
    if di>0: lns.append(o[di:di+500])
    return FormatResult("\n".join(lns), _tok(o), _tok("\n".join(lns)), "git show", "git_show")

# Tests
def pytest_format(o):
    ps = int(m.group(1)) if (m:=re.search(r'(\d+) passed', o)) else 0; fs = int(m.group(1)) if (m:=re.search(r'(\d+) failed', o)) else 0
    return FormatResult("\n".join([f"pytest {'FAIL' if fs else 'OK'} {ps}P {fs}F"]+[l for l in o.split("\n") if "FAIL" in l.upper() or "Error" in l or "assert" in l][:10]), _tok(o), _tok("\n".join([f"pytest"]+[l for l in o.split("\n")[:5]])), "pytest", "pytest")

def unittest_format(o):
    rn = int(m.group(1)) if (m:=re.search(r'Ran (\d+) tests', o)) else 0; ok = "OK" in o
    return FormatResult("\n".join([f"unittest: {'OK' if ok else 'FAIL'} ({rn} tests)"]+[l for l in o.split("\n") if "FAIL:" in l or "ERROR:" in l][:10]), _tok(o), _tok("\n".join([f"unittest: {rn}"])), "unittest", "unittest")

def jest_format(o):
    su = int(m.group(1)) if (m:=re.search(r'Test Suites: (\d+)', o)) else 0; ts = int(m.group(1)) if (m:=re.search(r'Tests:\s+(\d+)', o)) else 0
    fs = int(m.group(1)) if (m:=re.search(r'(\d+) failed', o)) else 0
    return FormatResult("\n".join([f"jest: {su}S {ts}T {fs}F"]+[l for l in o.split("\n") if "●" in l or "FAIL" in l][:10]), _tok(o), _tok("\n".join([f"jest: {su}S {ts}T"])), "jest", "jest")

def npm_test(o): return jest_format(o)

# Containers
def docker_ps(o):
    n = len([l for l in o.split("\n") if l.strip() and not l.startswith("CONTAINER")])
    return FormatResult("\n".join([f"docker: {n} containers"]+[l for l in o.split("\n")[1:11] if l.strip()]), _tok(o), _tok(f"docker: {n} containers"), "docker ps", "docker_ps")

def docker_images(o):
    n = len([l for l in o.split("\n") if l.strip() and not l.startswith("REPOSITORY")])
    return FormatResult("\n".join([f"docker: {n} images"]+[l for l in o.split("\n")[1:11] if l.strip()]), _tok(o), _tok(f"docker: {n} images"), "docker images", "docker_images")

def docker_logs(o):
    errs = [l for l in o.split("\n") if "ERROR" in l or "error" in l.lower()][:5]
    return FormatResult("\n".join([f"docker logs: {len(o.split(chr(10)))} lines, {len(errs)} errors"]+errs), _tok(o), _tok(f"docker logs: errors"), "docker logs", "docker_logs")

def kubectl_get(o):
    n = len([l for l in o.split("\n") if l.strip() and not l.startswith("NAME")])
    return FormatResult("\n".join([f"kubectl: {n} items"]+[l for l in o.split("\n")[1:12] if l.strip()]), _tok(o), _tok(f"kubectl: {n} items"), "kubectl get", "kubectl_get")

def kubectl_logs(o):
    errs = [l for l in o.split("\n") if "Error" in l or "ERROR" in l][:5]
    return FormatResult("\n".join([f"kubectl logs: {len(o.split(chr(10)))} lines"]+errs), _tok(o), _tok(f"kubectl logs"), "kubectl logs", "kubectl_logs")

# JS
def npm_install(o):
    ad = sum(int(m.group(1)) for m in re.finditer(r'added (\d+) packages', o))
    return FormatResult(f"npm: +{ad} packages", _tok(o), _tok(f"npm: +{ad}"), "npm install", "npm_install")

def pip_list(o):
    n = len([l for l in o.split("\n") if l.strip() and not l.startswith("Package")])
    return FormatResult(f"pip: {n} packages", _tok(o), _tok(f"pip: {n}"), "pip", "pip")

# System
def ls_fmt(o): n = len([l for l in o.split("\n") if l.strip()]); return FormatResult(f"ls: {n} items", _tok(o), _tok(f"ls: {n}"), "ls", "ls")
def find_fmt(o): n = len([l for l in o.split("\n") if l.strip()]); return FormatResult(f"find: {n} matches", _tok(o), _tok(f"find: {n}"), "find", "find")
def grep_fmt(o): n = len([l for l in o.split("\n") if l.strip()]); return FormatResult(f"grep: {n} matches", _tok(o), _tok(f"grep: {n}"), "grep", "grep")
def curl_fmt(o): s = re.search(r'HTTP/\d\.\d (\d+)', o); return FormatResult(f"curl: HTTP {s.group(1) if s else '?'}", _tok(o), _tok(f"curl: HTTP "), "curl", "curl")
def free_fmt(o): return FormatResult(f"free: {len(o.split(chr(10)))} lines", _tok(o), _tok("free"), "free", "free")

# Registry — 20 formatters
FORMATTERS = {
    "git status": git_status, "git diff": git_diff, "git log": git_log, "git show": git_show,
    "pytest": pytest_format, "unittest": unittest_format, "jest": jest_format, "npm test": npm_test,
    "docker ps": docker_ps, "docker images": docker_images, "docker logs": docker_logs,
    "kubectl get": kubectl_get, "kubectl logs": kubectl_logs,
    "npm install": npm_install, "pip": pip_list,
    "ls": ls_fmt, "find": find_fmt, "grep": grep_fmt, "curl": curl_fmt, "free": free_fmt,
}

def detect_command(command: str, output: str) -> str | None:
    cmd = command.lower().strip()
    for key in FORMATTERS:
        if all(w in cmd for w in key.split()): return key
    if "PASSED" in output or "FAIL" in output:
        if any(w in cmd for w in ("pytest","test","unittest")): return "pytest"
    if "●" in output and "Test Suites" in output: return "jest"
    if "CONTAINER ID" in output: return "docker ps"
    if "REPOSITORY" in output and "TAG" in output: return "docker images"
    if "NAME" in output and "READY" in output: return "kubectl get"
    if "Ran" in output and "tests" in output: return "unittest"
    return None

def format_output(command: str, output: str) -> FormatResult:
    key = detect_command(command, output)
    if key and key in FORMATTERS: return FORMATTERS[key](output)
    return FormatResult(output, _tok(output), _tok(output), command, "passthrough")
