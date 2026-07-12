═══════════════════════════════════════════════════
  Kettu Squeeze — Phase 4: Agent Quality Report
  Model: DeepSeek v4 Pro | Hermes Agent
═══════════════════════════════════════════════════

── Per-Scenario Results ──
  Scenario                               RAW    SQZ   ΔQual    ΔTok      NAB  Status
  -------------------------------------------------------------------------------------
  code_find_bug_auth                   100%  100%   +0.0%   +0.0%   +0.000  PASS
  code_refactor_worker                 100%  100%   +0.0%   +0.0%   +0.000  PASS
  code_architecture_question           100%  100%   +0.0%   +0.0%   +0.000  PASS
  code_write_test                      100%  100%   +0.0%   +0.0%   +0.000  PASS
  code_security_audit                  100%  100%   +0.0%   +0.0%   +0.000  PASS
  tool_pytest_mixed                    100%  100%   +0.0%   +0.0%   +0.000  PASS
  tool_docker_crash_loop               100%  100%   +0.0%  +25.3%   +0.076  PASS
  tool_large_json                      100%  100%   +0.0%  +26.5%   +0.079  PASS
  tool_git_diff_analysis               100%  100%   +0.0%   +0.0%   +0.000  PASS
  tool_k8s_crash                       100%  100%   +0.0%  -11.1%   -0.033  PASS
  long_session_200                     100%  100%   +0.0%   -1.6%   -0.005  PASS

── Aggregate ──
  Avg RAW recall:     100.0%
  Avg SQUEEZE recall: 100.0%
  Avg quality delta:  +0.00%
  Avg NAB:            +0.0107

── Verdict ──
  CONDITIONAL PASS — NAB +0.011 NEUTRAL, quality preserved

  Hard gates:
    Broken refs:          0
    Cross-session leaks:  0
    Byte-exact recovery:  100%
    Unicode panics:       0
    Quality degradation:  0.0% ≤ 3% PASS