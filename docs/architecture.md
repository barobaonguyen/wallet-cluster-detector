# Architecture

The repository is a literal five-stage Trawlkit-style loop:

```text
scrape                         score                 AI (optional)        alert                    schedule (optional)
clients/helius + enrichers ->  domain/cluster +  ->  commentary/gemini -> alert/telegram|discord -> schedule/cron
+ watchlist/discovery          domain/reasoner       neutral narration    channel dispatch          emit configs
```

The open-source part is the framework: collection, parsing, clustering, explanation, alerting, and paper trading. The private edge is your wallet list, tuned thresholds, scoring weights, and execution plan.

Related: [Trawlkit](https://github.com/baronguyen001/Trawlkit).
