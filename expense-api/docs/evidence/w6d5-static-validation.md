# W6D5 static validation (app repo)

All checks run 2026-07-15 against branch `w6d5-implementation`
(stacked on `w6d4-implementation` — see `w6d5-platform-gaps.md`).
No cluster or Argo CD sync is claimed.

## Gradle

```
$ ./gradlew :expense-api:test --console=plain
> Task :expense-api:compileJava UP-TO-DATE
> Task :expense-api:test UP-TO-DATE
BUILD SUCCESSFUL in 5s
```

Result: **PASS**. No app-code changes in this PR, so tests are cached.

## Shell script

Syntax check:

```
$ bash -n expense-api/scripts/w6d5-integration-spike.sh
$ echo $?
0
```

Dry-run:

```
$ DRY_RUN=1 COUNT=3 expense-api/scripts/w6d5-integration-spike.sh
[w6d5-spike] DRY_RUN=1: no AWS calls will be made.
[w6d5-spike] COUNT=3  TENANT=tenant-synth  FEATURE=categorize-expense
[w6d5-spike] QUEUE_URL (would-target)=<unset>
[w6d5-spike] Sample of first 3 messages:
  {"tenantId":"tenant-synth","feature":"categorize-expense","merchant":"Merchant-1","amount":2.0,"date":"2026-07-15","synthetic":true}
  {"tenantId":"tenant-synth","feature":"categorize-expense","merchant":"Merchant-2","amount":3.0,"date":"2026-07-15","synthetic":true}
  {"tenantId":"tenant-synth","feature":"categorize-expense","merchant":"Merchant-3","amount":4.0,"date":"2026-07-15","synthetic":true}
[w6d5-spike] Set DRY_RUN=0 and export QUEUE_URL to actually enqueue.
```

Result: **PASS**.

## k6 script

`k6` is not installed on the local box (`zsh: command not found: k6`).
Ran a plain JavaScript syntax check instead:

```
$ node --check expense-api/loadtests/expense-api-p99.js
$ echo $?
0
```

Result: **PASS** for parse. Full k6 semantic validation happens in the
`live` job of `.github/workflows/load.yml` when a target URL is
provided (see gaps doc).

## GitHub Actions workflow

```
$ ruby -ryaml -e 'YAML.load_stream(File.read(".github/workflows/load.yml")).size'
1
```

Result: **PASS** (parses as 1 YAML doc).

## Contract greps

### SLO thresholds copied verbatim

```
$ grep -n "p(99)<600" expense-api/loadtests/expense-api-p99.js
24:    http_req_duration: ["p(99)<600"],

$ grep -n "rate<0.01" expense-api/loadtests/expense-api-p99.js
26:    http_req_failed: ["rate<0.01"],

$ grep -n "p(95)<0.004" expense-api/loadtests/expense-api-p99.js
28:    cost_per_request_usd: ["p(95)<0.004"],
```

### Synthetic tenant only

```
$ grep -Rn "tenant-synth" expense-api/loadtests expense-api/scripts \
    expense-api/SRE-CAPSTONE.md
expense-api/loadtests/expense-api-p99.js:14:...tenant tenant-synth. No real...
expense-api/loadtests/expense-api-p99.js:49:const TENANT = "tenant-synth";
expense-api/scripts/w6d5-integration-spike.sh:14:TENANT="tenant-synth"
expense-api/SRE-CAPSTONE.md:...
```

### No API keys in W6D5 artifacts

```
$ grep -Rn "sk-" expense-api/loadtests expense-api/scripts/w6d5-integration-spike.sh
(no matches)

$ grep -Rn "LLM_API_KEY=" expense-api/loadtests expense-api/scripts/w6d5-integration-spike.sh
(no matches)
```

The workflow itself contains a `grep -RIn 'sk-\|LLM_API_KEY='` pattern
as a defensive assertion; that is code that scans for the pattern, not
a leaked secret. `expense-api/scripts/llm-cost-spike.sh` (W6D4)
contains `LLM_API_KEY=...` in a documentation comment telling the
operator to export the key from their shell, not to embed one in the
repo.

## Summary

| Check                                | Result |
| ------------------------------------ | ------ |
| `./gradlew :expense-api:test`        | PASS   |
| `bash -n` spike script               | PASS   |
| Spike DRY_RUN=1 COUNT=3              | PASS   |
| `node --check` k6 script             | PASS   |
| YAML parse `.github/workflows/load.yml` | PASS |
| grep SLO thresholds (3)              | PASS   |
| grep tenant-synth                    | PASS   |
| grep secrets (`sk-`, `LLM_API_KEY=`) | PASS   |

No live-cluster / k6 / X-Ray / Tempo evidence is claimed here.
