# Helius Survival Demo

This demo uses dummy keys and monkeypatches the HTTP request method. It does not call Helius.

```bash
python examples/helius_survival/demo.py
```

It shows key rotation on a simulated `"max usage reached"` response and budget short-circuit behavior.
