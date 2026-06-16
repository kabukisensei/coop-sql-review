# SQL Standards

## 1. Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| Tables | `layer.object_name` | `bronze.raw_d365_contact`, `silver.dim_customer` |
| CTEs | `cte_descriptive_name` | `cte_cleaned_contacts` |
| Columns — Bronze | `raw_source_names` (preserve source) | `contactid`, `firstname`, `createdon` |
| Columns — Silver/Gold | `PascalCase` | `CustomerId`, `FirstName`, `CreatedDate` |

### Column Naming by Layer

**Bronze:** Preserve raw source column names exactly as they come from the source system.

```sql
-- Bronze: Raw names from Dynamics 365
SELECT 
    contactid,
    firstname,
    lastname,
    emailaddress1,
    createdon,
    modifiedon,
    statecode
FROM bronze.raw_d365_contact;
```

**Silver/Gold:** Convert to PascalCase for consistency and readability.

```sql
-- Silver: Cleaned and renamed
SELECT 
    contactid AS CustomerId,
    firstname AS FirstName,
    lastname AS LastName,
    emailaddress1 AS EmailAddress,
    createdon AS CreatedDate,
    modifiedon AS ModifiedDate,
    statecode AS StateCode
FROM bronze.raw_d365_contact;
```

## 2. Descriptive Aliases — Never `a.id = b.id`

Always use meaningful table aliases that describe the entity, not single letters.

```sql
-- Good: Descriptive aliases
SELECT 
    cust.CustomerId,
    cust.FirstName,
    cust.LastName,
    addr.City,
    addr.State
FROM silver.dim_customer cust
LEFT JOIN silver.dim_address addr ON cust.CustomerId = addr.CustomerId;

-- Bad: Single-letter aliases
SELECT 
    a.CustomerId,
    a.FirstName,
    b.City
FROM silver.dim_customer a
LEFT JOIN silver.dim_address b ON a.CustomerId = b.CustomerId;
```

**Rules:**
- Use 3-5 character abbreviations of the table name
- `dim_customer` → `cust`
- `dim_address` → `addr`
- `fact_sales_daily` → `sales`
- `fact_opportunity` → `opp`
- `cte_active_customers` → `actCust`

## 3. SELECT Alias Matches INSERT Target

Always alias the SELECT statement columns to match the INSERT target. This makes it easy to verify column alignment at a glance.

```sql
-- Good: Aliases match INSERT target exactly
INSERT INTO silver.dim_customer (
    CustomerId,
    FirstName,
    LastName,
    EmailAddress,
    CreatedDate,
    ModifiedDate,
    EffectiveDate,
    ExpirationDate,
    IsCurrent
)
SELECT 
    src.contactid AS CustomerId,
    src.firstname AS FirstName,
    src.lastname AS LastName,
    src.emailaddress1 AS EmailAddress,
    src.createdon AS CreatedDate,
    src.modifiedon AS ModifiedDate,
    @effective_date AS EffectiveDate,
    '9999-12-31' AS ExpirationDate,
    1 AS IsCurrent
FROM bronze.raw_d365_contact src
WHERE src.statecode = 0;

-- Bad: No aliases — hard to verify column alignment
INSERT INTO silver.dim_customer
SELECT 
    contactid,
    firstname,
    lastname,
    emailaddress1,
    createdon,
    modifiedon,
    @effective_date,
    '9999-12-31',
    1
FROM bronze.raw_d365_contact;
```

**Rule:** Every column in the SELECT must have an `AS` alias that matches the INSERT column name.

## 4. CTEs Over Subqueries

```sql
-- Good
WITH cte_source AS (
    SELECT contactid, firstname, lastname
    FROM bronze.raw_d365_contact
    WHERE statecode = 0
),
cte_deduped AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY contactid ORDER BY modifiedon DESC) AS rn
    FROM cte_source
)
SELECT contactid, firstname, lastname
FROM cte_deduped
WHERE rn = 1;

-- Bad
SELECT contactid, firstname, lastname
FROM (
    SELECT contactid, firstname, lastname,
           ROW_NUMBER() OVER (PARTITION BY contactid ORDER BY modifiedon DESC) AS rn
    FROM bronze.raw_d365_contact
    WHERE statecode = 0
) sub
WHERE sub.rn = 1;
```

## 5. Upsert Patterns — MERGE vs CTAS

### Context

Microsoft Fabric Data Warehouse has specific behaviors that affect upsert strategy:

- **MERGE** is supported but has limitations in Fabric DW (preview, table-level conflict detection, can cause snapshot isolation conflicts)
- **CTAS (CREATE TABLE AS SELECT)** is the preferred pattern for large-scale transforms — parallel, single-operation, no logging overhead
- **DELETE + INSERT** is the recommended production pattern for upserts per Microsoft Fabric best practices

### Preferred: CTAS + sp_rename (Large Tables)

For large fact tables or full refreshes, use CTAS for optimal performance:

```sql
-- Step 1: Create new version of the table with all data
CREATE TABLE gold.fact_sales_daily_new
WITH
(
    DISTRIBUTION = HASH(SalesId),
    CLUSTERED COLUMNSTORE INDEX
)
AS
SELECT 
    s.SalesId,
    s.SalesDate,
    s.CustomerId,
    s.ProductId,
    s.Revenue,
    s.Quantity,
    s.HashKey,
    GETDATE() AS EtlTimestamp
FROM gold.fact_sales_daily s
WHERE s.SalesDate < @watermark_date  -- Keep existing data

UNION ALL

SELECT 
    stg.SalesId,
    stg.SalesDate,
    stg.CustomerId,
    stg.ProductId,
    stg.Revenue,
    stg.Quantity,
    stg.HashKey,
    GETDATE() AS EtlTimestamp
FROM cte_staging stg;  -- New/updated data

-- Step 2: Swap tables (metadata-only operation)
RENAME OBJECT gold.fact_sales_daily TO fact_sales_daily_old;
RENAME OBJECT gold.fact_sales_daily_new TO fact_sales_daily;

-- Step 3: Drop old table
DROP TABLE gold.fact_sales_daily_old;
```

**When to use CTAS:**
- Full table refreshes
- Large fact tables (>1M rows)
- When you need to change distribution or indexing
- When MERGE would conflict with concurrent operations

### Alternative: DELETE + INSERT (Incremental)

For incremental updates where you need to preserve table structure and indexes:

```sql
-- Step 1: Delete existing records that will be updated
DELETE FROM gold.fact_sales_daily
WHERE SalesId IN (SELECT SalesId FROM cte_staging);

-- Step 2: Insert all records (new + updated)
INSERT INTO gold.fact_sales_daily (
    SalesId, SalesDate, CustomerId, ProductId, Revenue, Quantity, HashKey, EtlTimestamp
)
SELECT 
    SalesId, SalesDate, CustomerId, ProductId, Revenue, Quantity, HashKey, GETDATE()
FROM cte_staging;
```

**When to use DELETE + INSERT:**
- Incremental updates (<20% of table)
- Need to preserve indexes and constraints
- Lower risk than CTAS for small changes

### MERGE (Use with Caution)

MERGE is acceptable for small dimension tables or when you need atomic upsert semantics:

```sql
-- Only for small dimension tables (<100K rows)
MERGE silver.dim_customer AS target
USING cte_staging AS source
ON target.CustomerId = source.CustomerId
WHEN MATCHED AND source.HashKey <> target.HashKey THEN
    UPDATE SET
        target.FirstName = source.FirstName,
        target.LastName = source.LastName,
        target.ModifiedDate = source.ModifiedDate,
        target.HashKey = source.HashKey
WHEN NOT MATCHED THEN
    INSERT (CustomerId, FirstName, LastName, CreatedDate, ModifiedDate, HashKey)
    VALUES (source.CustomerId, source.FirstName, source.LastName, GETDATE(), GETDATE(), source.HashKey);
```

**MERGE cautions in Fabric DW:**
- Can cause snapshot isolation conflicts under concurrent load
- Table-level locking during operation
- Less performant than CTAS for large datasets
- Prefer DELETE+INSERT or CTAS for production workloads

### Decision Guide

| Scenario | Recommended Pattern |
|----------|-------------------|
| Full refresh, large table | CTAS + sp_rename |
| Incremental update, large table | DELETE + INSERT |
| Small dimension table (<100K) | MERGE or DELETE + INSERT |
| Need atomic upsert semantics | MERGE (small tables only) |
| Changing distribution/index | CTAS + sp_rename |

## 6. SCD Type 2 Pattern

```sql
-- Close existing record
UPDATE silver.dim_customer
SET ExpirationDate = @effective_date,
    IsCurrent = 0
WHERE CustomerId = @customer_id
  AND IsCurrent = 1;

-- Insert new record
INSERT INTO silver.dim_customer (CustomerId, FirstName, LastName, EffectiveDate, ExpirationDate, IsCurrent)
VALUES (@customer_id, @first_name, @last_name, @effective_date, '9999-12-31', 1);
```

## 7. EXISTS / NOT EXISTS — Comment the Reasoning

When using `EXISTS` or `NOT EXISTS`, always include a comment explaining **why** this pattern is chosen over alternatives.

```sql
-- Good: EXISTS with reasoning comment
-- Using EXISTS instead of COUNT(*) because we only need to know if 
-- at least one open opportunity exists, not how many.
-- EXISTS short-circuits on first match; COUNT(*) scans all rows.
SELECT cust.CustomerId, cust.FirstName
FROM silver.dim_customer cust
WHERE EXISTS (
    SELECT 1
    FROM gold.fact_opportunity opp
    WHERE opp.CustomerId = cust.CustomerId
      AND opp.Status = 'Open'
      AND opp.CreatedDate >= DATEADD(day, -90, GETDATE())
);

-- Good: NOT EXISTS with reasoning comment
-- Using NOT EXISTS to find customers with no sales in the last 12 months.
-- LEFT JOIN + IS NULL would work but NOT EXISTS is clearer intent 
-- and handles NULL CustomerIds safely.
SELECT cust.CustomerId, cust.FirstName
FROM silver.dim_customer cust
WHERE cust.IsCurrent = 1
  AND NOT EXISTS (
      SELECT 1
      FROM gold.fact_sales_daily sales
      WHERE sales.CustomerId = cust.CustomerId
        AND sales.SalesDate >= DATEADD(month, -12, GETDATE())
  );

-- Bad: No comment explaining why EXISTS was chosen
SELECT CustomerId, FirstName
FROM silver.dim_customer
WHERE EXISTS (
    SELECT 1 FROM gold.fact_opportunity WHERE CustomerId = dim_customer.CustomerId
);
```

**Rule:** If you use `EXISTS` or `NOT EXISTS`, add a comment block above it explaining:
1. What you're checking for
2. Why `EXISTS` is better than the alternative (`COUNT(*)`, `LEFT JOIN + IS NULL`, `IN`, etc.)

## 8. Join Simplicity — Push Filtering Upstream

Keep joins simple. Move filtering logic to CTEs or earlier in the stored procedure so joins operate on already-filtered datasets.

```sql
-- Good: Filter in CTE first, then join with descriptive aliases
-- Filtering applied upstream so the join works on a smaller dataset
WITH cte_active_customers AS (
    -- Only current customers in target market
    SELECT CustomerId, FirstName, TerritoryId
    FROM silver.dim_customer
    WHERE IsCurrent = 1
      AND MarketSegment = 'Enterprise'
),
cte_recent_sales AS (
    -- Only sales from last 90 days
    SELECT CustomerId, SUM(Revenue) AS TotalRevenue
    FROM gold.fact_sales_daily
    WHERE SalesDate >= DATEADD(day, -90, GETDATE())
    GROUP BY CustomerId
)
SELECT 
    cust.CustomerId,
    cust.FirstName,
    cust.TerritoryId,
    COALESCE(sales.TotalRevenue, 0) AS RecentRevenue
FROM cte_active_customers cust
LEFT JOIN cte_recent_sales sales ON cust.CustomerId = sales.CustomerId;

-- Bad: Complex join with filtering in the ON clause
SELECT 
    c.CustomerId,
    c.FirstName,
    SUM(s.Revenue) AS RecentRevenue
FROM silver.dim_customer c
LEFT JOIN gold.fact_sales_daily s 
    ON c.CustomerId = s.CustomerId
    AND s.SalesDate >= DATEADD(day, -90, GETDATE())  -- Filter in join
    AND c.IsCurrent = 1                               -- Filter in join
    AND c.MarketSegment = 'Enterprise'                -- Filter in join
GROUP BY c.CustomerId, c.FirstName;
```

**Rules:**
- Filter data in CTEs before joining when possible
- Join conditions should be simple: `ON cust.CustomerId = sales.CustomerId`
- Avoid putting business logic (filters, CASE, functions) in JOIN clauses
- Use source tables directly in joins rather than nested views when possible

## 9. Fabric DW-Specific Rules

### Data Types

Fabric Data Warehouse does NOT support these T-SQL types. Use the alternatives:

| Do NOT Use | Use Instead | Notes |
|-----------|-------------|-------|
| `nvarchar` | `varchar` | Fabric DW uses UTF-8 encoding; `varchar` is Unicode-safe |
| `datetime` | `datetime2` | More precision, smaller storage |
| `money` | `decimal(19,4)` | Exact precision, avoids rounding issues |
| `text` | `varchar(max)` | Standard T-SQL pattern |
| `ntext` | `varchar(max)` | Standard T-SQL pattern |
| `image` | `varbinary(max)` | Standard T-SQL pattern |

```sql
-- Good: Fabric DW compatible types
CREATE TABLE gold.fact_sales_daily (
    SalesId         bigint          NOT NULL,
    SalesDate       date            NOT NULL,
    CustomerId      bigint          NOT NULL,
    ProductId       bigint          NOT NULL,
    Revenue         decimal(19,4)   NOT NULL,  -- Not money
    Quantity        int             NOT NULL,
    Description     varchar(500)    NULL,       -- Not nvarchar
    CreatedDateTime datetime2       NOT NULL,   -- Not datetime
    HashKey         varchar(64)     NOT NULL
);
```

### CTAS Best Practices

```sql
-- Good: Explicit CAST in CTAS to control output types
CREATE TABLE gold.fact_monthly_summary
WITH
(
    DISTRIBUTION = HASH(MonthKey),
    CLUSTERED COLUMNSTORE INDEX
)
AS
SELECT 
    CAST(YEAR(SalesDate) * 100 + MONTH(SalesDate) AS int) AS MonthKey,
    CAST(SUM(Revenue) AS decimal(19,4)) AS TotalRevenue,  -- Explicit type
    CAST(COUNT(*) AS bigint) AS TransactionCount,
    CAST(AVG(Revenue) AS decimal(19,4)) AS AvgRevenue
FROM gold.fact_sales_daily
GROUP BY YEAR(SalesDate), MONTH(SalesDate);
```

### Singleton INSERTs

Avoid singleton `INSERT ... VALUES` at scale — creates tiny Parquet files and poor performance:

```sql
-- Bad: Singleton inserts create tiny files
INSERT INTO gold.fact_sales_daily VALUES (1, '2026-01-01', 100, 200, 99.99, 1, 'abc', GETDATE());
INSERT INTO gold.fact_sales_daily VALUES (2, '2026-01-01', 101, 201, 49.99, 2, 'def', GETDATE());

-- Good: Batch insert from SELECT
INSERT INTO gold.fact_sales_daily (
    SalesId, SalesDate, CustomerId, ProductId, Revenue, Quantity, HashKey, EtlTimestamp
)
SELECT 
    SalesId, SalesDate, CustomerId, ProductId, Revenue, Quantity, HashKey, GETDATE()
FROM cte_staging;

-- Best: CTAS for large loads
CREATE TABLE gold.fact_sales_daily_new
WITH (DISTRIBUTION = HASH(SalesId), CLUSTERED COLUMNSTORE INDEX)
AS SELECT * FROM cte_staging;
```

### Schema Evolution

`ALTER COLUMN` is not supported in Fabric DW. Use CTAS workaround:

```sql
-- Need to change Revenue from decimal(10,2) to decimal(19,4)?
-- Step 1: Create new table with correct schema
CREATE TABLE gold.fact_sales_daily_v2
WITH
(
    DISTRIBUTION = HASH(SalesId),
    CLUSTERED COLUMNSTORE INDEX
)
AS
SELECT 
    SalesId,
    SalesDate,
    CustomerId,
    ProductId,
    CAST(Revenue AS decimal(19,4)) AS Revenue,  -- New type
    Quantity,
    HashKey,
    EtlTimestamp
FROM gold.fact_sales_daily;

-- Step 2: Swap
RENAME OBJECT gold.fact_sales_daily TO fact_sales_daily_old;
RENAME OBJECT gold.fact_sales_daily_v2 TO fact_sales_daily;
DROP TABLE gold.fact_sales_daily_old;
```

### Transactions

- Fabric DW uses **snapshot isolation only**
- Long transactions increase conflict window
- Keep transactions as short as possible
- Serialize writes to the same table to avoid conflicts

```sql
-- Good: Short transaction, explicit commit
BEGIN TRANSACTION;
DELETE FROM gold.fact_sales_daily WHERE SalesDate = @process_date;
INSERT INTO gold.fact_sales_daily SELECT * FROM cte_staging WHERE SalesDate = @process_date;
COMMIT;
```

### Query Labeling

Label authoring queries for monitoring and diagnostics:

```sql
-- Add OPTION (LABEL) to track ETL operations
INSERT INTO gold.fact_sales_daily
SELECT * FROM cte_staging
OPTION (LABEL = 'ETL_DailySales_Load_20260604');
```

### Connection Requirements

```sql
-- Always specify database name with sqlcmd
sqlcmd -S "endpoint.datawarehouse.fabric.microsoft.com" -d "DatabaseName" -G

-- -G = ActiveDirectoryDefault (uses az login session)
-- No SQL authentication in Fabric DW
```

## 10. Header Comments (Every SQL File)

```sql
/*
  File: silver/dim_customer.sql
  Purpose: Clean and deduplicate customer data from Dynamics 365
  Source: bronze.raw_d365_contact
  Author: Aaron Jennings
  Date: 2026-06-01
  Change Log:
    2026-06-01: Initial version
    2026-06-03: Added SCD Type 2 tracking
*/
```

## 11. Checklist Before Committing SQL

- [ ] CTEs used instead of subqueries
- [ ] Descriptive aliases on all tables (not single letters)
- [ ] SELECT aliases match INSERT target columns
- [ ] Bronze uses raw source names; Silver/Gold uses PascalCase
- [ ] Comments on complex logic
- [ ] **Upsert pattern appropriate** — CTAS for large/full refreshes, DELETE+INSERT for incremental, MERGE only for small dimensions
- [ ] SCD pattern correct (if applicable)
- [ ] No SELECT * in production code
- [ ] Date filters use parameters
- [ ] EXISTS / NOT EXISTS have reasoning comments
- [ ] Filtering logic pushed to CTEs (not in JOIN clauses)
- [ ] Joins use source tables directly when possible
- [ ] **Fabric DW data types verified** — no `nvarchar`/`datetime`/`money` (use `varchar`/`datetime2`/`decimal` instead)
- [ ] **No singleton INSERT VALUES at scale** — use INSERT...SELECT, CTAS, or COPY INTO
- [ ] **No ALTER COLUMN** — use CTAS workaround for schema evolution
- [ ] **Transactions kept short** — long transactions increase conflict window

## 14. References

- [Microsoft Fabric Skills for GitHub Copilot](https://github.com/microsoft/skills-for-fabric) — Official Microsoft-authored Fabric skills (MIT license)
- [Microsoft Fabric SQLDW Authoring Skill](https://github.com/microsoft/skills-for-fabric/tree/main/skills/sqldw-authoring-cli) — T-SQL patterns, CTAS, COPY INTO, time travel
- [Microsoft Fabric Medallion Architecture Skill](https://github.com/microsoft/skills-for-fabric/tree/main/skills/e2e-medallion-architecture) — Bronze/Silver/Gold patterns
- [Microsoft Fabric Semantic Model Authoring](https://github.com/microsoft/skills-for-fabric/tree/main/skills/semantic-model-authoring) — TMDL, DAX, deployment
- [Microsoft Fabric Community Blog](https://community.fabric.microsoft.com/t5/Fabric-Updates-Blog/Fabric-Skills-for-GitHub-Copilot-Claude-and-CLI-built-by/ba-p/5190188) — Announcement and overview

> **Note:** Microsoft updates their skills repository regularly. This agent checks for updates weekly and patches new guidance into these standards as needed.
