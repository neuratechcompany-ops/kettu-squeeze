# Reproducibility Guide — Kettu Squeeze v0.3

## Quick Reproduce

```bash
git clone https://github.com/neuratechcompany-ops/kettu-squeeze
cd kettu-squeeze
git checkout e2ec835
pip install -e ".[dev]"
pytest tests/ -q  # 281 PASS

# Comparative evaluation
pip install -e /path/to/kettu-eval
python scripts/comparative_eval.py
```

## Dataset

context-core v1.0.0 from Kettu Eval. Checksum: sha256:cce1fadc

## Config

- Policy: AdaptivePolicyEngine v0.2.0
- Strategies: 8 (log, json, python, traceback, test_output, diff, markdown, conversation)
- Budget: 131072 tokens
- Tokenizer: len//3 heuristic

## Known Limitations

- SQZ unavailable (binary 404 for aarch64-apple-darwin)
- Fidelity measured on content-actual strings only
- Strategy dispatch format-dependent
