/*
  File: silver/dim_customer.sql
  Purpose: smoke fixture
*/
CREATE VIEW silver.dim_customer AS
WITH cte_source AS (
    SELECT *  -- intermediate CTE: allowed
    FROM bronze.raw_d365_contact
)
SELECT *      -- production select: flagged
FROM cte_source;
GO

SELECT COUNT(*) AS n FROM silver.dim_customer;
GO
