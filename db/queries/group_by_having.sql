SET search_path TO expense, public;

SELECT
    m.id           AS merchant_id,
    m.display_name AS display_name,
    COUNT(t.id)    AS transaction_count,
    AVG(t.amount)  AS average_amount
FROM expense.merchant AS m
INNER JOIN expense.transaction AS t
    ON t.merchant_id = m.id
GROUP BY m.id, m.display_name
HAVING COUNT(t.id) >= 1
ORDER BY average_amount DESC, m.id;
