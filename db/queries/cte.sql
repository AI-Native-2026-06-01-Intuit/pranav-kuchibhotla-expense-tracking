SET search_path TO expense, public;

WITH merchant_totals AS (
    SELECT
        t.merchant_id   AS merchant_id,
        COUNT(t.id)     AS transaction_count,
        SUM(t.amount)   AS total_amount
    FROM expense.transaction AS t
    GROUP BY t.merchant_id
)
SELECT
    m.id                    AS merchant_id,
    m.display_name          AS display_name,
    mt.transaction_count    AS transaction_count,
    mt.total_amount         AS total_amount
FROM merchant_totals AS mt
INNER JOIN expense.merchant AS m
    ON m.id = mt.merchant_id
WHERE mt.total_amount >= 50.00
ORDER BY mt.total_amount DESC, m.id;
