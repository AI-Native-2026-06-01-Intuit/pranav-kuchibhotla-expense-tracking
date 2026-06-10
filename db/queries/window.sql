SET search_path TO expense, public;

SELECT
    t.id           AS transaction_id,
    t.merchant_id  AS merchant_id,
    m.display_name AS display_name,
    t.amount       AS amount,
    t.occurred_at  AS occurred_at,
    RANK() OVER (
        PARTITION BY t.merchant_id
        ORDER BY t.amount DESC
    )              AS amount_rank,
    SUM(t.amount) OVER (
        PARTITION BY t.merchant_id
    )              AS merchant_total
FROM expense.transaction AS t
INNER JOIN expense.merchant AS m
    ON m.id = t.merchant_id
ORDER BY t.merchant_id, amount_rank, t.id;
