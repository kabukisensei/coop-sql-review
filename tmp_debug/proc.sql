
CREATE PROCEDURE dbo.GetCustomer
AS
    SELECT *
    FROM dbo.Customers
    WHERE CustomerName = 123;
