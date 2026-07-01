-- File: realistic_estate.sql
-- Purpose: a realistic multi-batch Fabric DW script (proc with TRY/CATCH +
--          transaction, CTE insert, temp table, UPDATE FROM, MERGE, TOP/ORDER
--          BY view, DDL/WHILE existence guards, windowed DISTINCT, GO <count>)
--          so the corpus crash-guard exercises every rule over common syntax.
CREATE VIEW gold.v_top_customers AS
SELECT TOP 10 rev.CustomerId, rev.Revenue
FROM gold.fact_revenue AS rev
ORDER BY rev.Revenue DESC;
GO 2
CREATE PROCEDURE silver.usp_load_dim_customer
AS
BEGIN
    SET NOCOUNT ON;

    BEGIN TRY
        BEGIN TRANSACTION;

        CREATE TABLE #stage (
            CustomerId   BIGINT        NOT NULL,
            FirstName    NVARCHAR(50)  NULL,
            RegionCode   VARCHAR(10)   NOT NULL,
            LoadDate     DATETIME2(3)  NOT NULL
        );

        INSERT INTO #stage (CustomerId, FirstName, RegionCode, LoadDate)
        SELECT src.CustomerId, src.FirstName, src.RegionCode, src.LoadDate
        FROM bronze.customer_raw AS src
        WHERE src.LoadDate >= '2026-01-01';

        WITH cte_latest AS (
            SELECT stg.CustomerId,
                   stg.FirstName,
                   stg.LoadDate,
                   ROW_NUMBER() OVER (PARTITION BY stg.CustomerId ORDER BY stg.LoadDate DESC) AS rn
            FROM #stage AS stg
        )
        INSERT INTO silver.dim_customer (CustomerId, FirstName, LoadDate)
        SELECT cte.CustomerId, cte.FirstName, cte.LoadDate
        FROM cte_latest AS cte
        WHERE cte.rn = 1;

        UPDATE tgt
        SET tgt.FirstName = src.FirstName
        FROM silver.dim_customer AS tgt
        JOIN #stage AS src
          ON CAST(tgt.CustomerId AS VARCHAR(20)) = CAST(src.CustomerId AS VARCHAR(20));

        MERGE silver.dim_region AS tgt
        USING (SELECT DISTINCT stg.RegionCode FROM #stage AS stg) AS src
            ON tgt.RegionCode = src.RegionCode
        WHEN NOT MATCHED THEN
            INSERT (RegionCode) VALUES (src.RegionCode);

        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0
            ROLLBACK TRANSACTION;
        THROW;
    END CATCH
END;
GO
IF (NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'work_queue'))
BEGIN
    CREATE TABLE dbo.work_queue (Id INT NOT NULL);
END
GO
WHILE (EXISTS (SELECT 1 FROM dbo.work_queue))
BEGIN
    DELETE TOP (10) FROM dbo.work_queue;
END
GO
SELECT DISTINCT ord.CustomerId,
       SUM(ord.Amount) OVER (PARTITION BY ord.CustomerId) AS TotalAmount
FROM gold.fact_orders AS ord
WHERE ord.OrderDate >= DATEADD(day, -90, GETDATE());
