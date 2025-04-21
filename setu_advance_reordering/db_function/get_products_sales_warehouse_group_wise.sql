DROP FUNCTION IF EXISTS public.get_products_sales_warehouse_group_wise(integer[], integer[], integer[], integer[], date, date);
CREATE OR REPLACE FUNCTION public.get_products_sales_warehouse_group_wise(
    IN company_ids integer[],
    IN product_ids integer[],
    IN category_ids integer[],
    IN warehouse_ids integer[],
    IN start_date date,
    IN end_date date)
RETURNS TABLE(product_id integer, product_name character varying, warehouse_id integer, sales numeric, sales_return numeric, total_sales numeric, ads numeric) AS
--RETURNS TABLE(product_id integer, product_name character varying, sales numeric, sales_return numeric, total_sales numeric, ads numeric) AS
$BODY$
    DECLARE
        day_difference integer := ((end_date::Date-start_date::Date)+1);
--        temprow record;
--        tr_date_start timestamp without time zone := (date_start || ' 00:00:00')::timestamp without time zone;
    BEGIN
    Drop Table if exists transaction_table;
    CREATE TEMPORARY TABLE transaction_table(
        product_id INT,
        product_name character varying,
        warehouse_id INT,
        sales Numeric DEFAULT 0,
        sales_return numeric DEFAULT 0);

    -- Sales
    Insert into transaction_table(product_id, product_name, warehouse_id, sales)
    select T.product_id, T.product_name, T.warehouse_id, product_qty
    from get_stock_data(company_ids, product_ids, category_ids, warehouse_ids, 'sales', start_date, end_date)T;

    -- Sales Return
    Insert into transaction_table(product_id, product_name, warehouse_id, sales_return)
    select T.product_id, T.product_name, T.warehouse_id, product_qty
    from get_stock_data(company_ids, product_ids, category_ids, warehouse_ids, 'sales_return', start_date, end_date)T;


    RETURN QUERY
    Select Tr_data.*, case when (Tr_data.sales - Tr_data.sales_return) > 0 then (Tr_data.sales - Tr_data.sales_return) else 0 end as total_sales,
    case when (Tr_data.sales - Tr_data.sales_return) > 0 then (Tr_data.sales - Tr_data.sales_return) / day_difference else 0 end as ads
    From
    (
    Select
    T.product_id, T.product_name,
    T.warehouse_id,
    sum(T.sales) as sales,
    sum(T.sales_return) as sales_return
    From
    transaction_table T
    group by
    T.product_id, T.product_name
    ,T.warehouse_id
    )Tr_data;

END; $BODY$
LANGUAGE plpgsql VOLATILE
COST 100
ROWS 1000;