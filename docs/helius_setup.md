# Helius Setup

Helius free credits are monthly. Treat the quota as a scarce resource:

- Poll signatures first, then parse only new signatures.
- Keep RPS below the published limit.
- Rotate keys only when Helius says a key reached usage limits.
- Open a circuit when repeated 429s show the service or key is not ready.
- Persist local credit counters so restarts do not forget usage.

The client never prints API keys and redacts `api-key=` values in logs.
