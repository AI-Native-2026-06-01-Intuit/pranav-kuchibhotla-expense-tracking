# W6D4 alarm drill evidence

The W6D4 cost alarm was drilled by publishing synthetic datapoints to the same CloudWatch metric that the LLM cost middleware emits:

- Namespace: `acme/llmproxy`
- Metric: `CostUsd`
- Dimensions: same as the deployed alarm
- Low datapoints established the pre-spike OK state.
- High datapoints forced the mid-spike ALARM state.
- Low recovery datapoints restored OK after the 3 x 5-minute evaluation window.

Raw local evidence was captured under `/tmp/w6d4-alarm-drill/`:

- `01-pre-spike-ok.txt`
- `02-mid-spike-alarm.txt`
- `03-post-spike-recovery.txt`

Reviewer-facing excerpts are pasted into the config PR body.
