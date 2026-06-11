# Advanced SQL Queries

Reference SQL for the `expense` schema (see `db/V1__schema.sql`), exercising
joins, CTEs, window functions, and `GROUP BY` + `HAVING`. All four files run
cleanly after applying `db/V1__schema.sql` and `db/V2__seed.sql`.

## Query catalogue

### `joins.sql`

**Business question:** Which merchants do our transactions belong to, and
which merchants have never been transacted with? **Tables touched:**
`expense.transaction`, `expense.merchant`. **SQL idiom:** `INNER JOIN` to
list every transaction with its merchant's display name and kind, plus a
`LEFT JOIN` + `COUNT` so merchants with zero transactions still appear with
`transaction_count = 0`.

### `cte.sql`

**Business question:** Which merchants account for at least $50.00 of total
spend, and how many transactions made up that total? **Tables touched:**
`expense.transaction`, `expense.merchant`. **SQL idiom:** A `WITH
merchant_totals AS (...)` common-table expression aggregates per merchant
once, and the outer `SELECT` joins it back to `expense.merchant` and filters
on `total_amount >= 50.00`.

### `window.sql`

**Business question:** For each merchant, rank its transactions by amount
(highest first) while also showing the merchant's overall total alongside
every row. **Tables touched:** `expense.transaction`, `expense.merchant`.
**SQL idiom:** Window functions —
`RANK() OVER (PARTITION BY merchant_id ORDER BY amount DESC)` for the rank
and `SUM(amount) OVER (PARTITION BY merchant_id)` for the per-merchant
total. One row per transaction is preserved.

### `group_by_having.sql`

**Business question:** Which merchants have at least one transaction, and
what is the average transaction amount per merchant? **Tables touched:**
`expense.transaction`, `expense.merchant`. **SQL idiom:** `GROUP BY` on
`merchant.id`/`merchant.display_name` with `HAVING COUNT(t.id) >= 1` to
require at least one transaction (the aggregate filter is the point of
`HAVING` vs. `WHERE`).

## Running locally

Apply the schema and seed first, then run any query file:

```bash
psql postgres -f db/V1__schema.sql
psql postgres -f db/V2__seed.sql
psql postgres -f db/queries/joins.sql
psql postgres -f db/queries/cte.sql
psql postgres -f db/queries/window.sql
psql postgres -f db/queries/group_by_having.sql
```

`db/V2__seed.sql` intentionally finishes with a negative-amount `INSERT`
wrapped in its own `BEGIN`/`ROLLBACK` block. When you apply the seed via
`psql`, you will see one `ERROR: ... violates check constraint
"transaction_amount_non_negative"` printed after the committed seed
transaction — that failure is **expected** and proves the
`amount >= 0` constraint fires. The committed seed rows are not affected.

## Running in tests

```bash
./gradlew test --tests "*QueryIT"
```

Testcontainers starts a Postgres 16 container, applies the schema + seed,
runs the queries, and stops the container automatically. No manual
`docker run` is required.

In this Rancher Desktop environment the wrapper command needs the Docker
socket override and a pinned Docker API version:

```bash
DOCKER_HOST="unix://$HOME/.rd/docker.sock" \
TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE="/var/run/docker.sock" \
JAVA_TOOL_OPTIONS="-Dapi.version=1.41 -Ddocker.api.version=1.41" \
./gradlew --no-daemon test --tests "*QueryIT"
```

## Trade-offs

**Why `cte.sql` uses a CTE instead of an inline subquery.** The CTE
`merchant_totals` names the per-merchant aggregate once, so the outer query
reads as "join merchants to their totals and filter" — the intent is on the
surface. An inline subquery would force the reader to parse the aggregate
and the join in one breath, and any future query that needs the same
per-merchant totals (e.g. a ranking, a second filter) would have to repeat
the aggregate. The CTE keeps the aggregation a single, named, reusable
step at no runtime cost for a query of this shape.

**Why `window.sql` is not replaceable with `GROUP BY`.** `GROUP BY` would
collapse each merchant down to a single aggregated row, which destroys the
per-transaction detail. The business question here is per-transaction
("for each transaction, what is its rank within its merchant, and what is
the merchant's overall total?"), so the result must keep one row per
transaction. `RANK() OVER (...)` and `SUM(amount) OVER (...)` add the rank
and the per-merchant total as extra columns alongside every transaction
row without aggregating them away — exactly what a window function is for.
