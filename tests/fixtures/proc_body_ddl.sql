-- File: proc_body_ddl.sql
-- Purpose: a proc whose body creates tables — pins that body DDL is visible
--          to the parser and rules (it used to be silently skipped).
CREATE PROCEDURE silver.usp_build_pricing
AS
BEGIN
    CREATE TABLE silver.dim_pricing (
        PriceId     BIGINT       NOT NULL,
        ListPrice   MONEY        NOT NULL,
        CreatedDt   DATETIME     NULL,
        Descr       NVARCHAR(50) NULL
    );

    CREATE TABLE staging.price_work (Id INT NOT NULL);
END;
GO
CREATE TABLE gold.fact_price (PriceId BIGINT NOT NULL);
