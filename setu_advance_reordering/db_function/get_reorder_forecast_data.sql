DROP FUNCTION IF EXISTS get_reorder_forecast_data(character varying, character varying, character varying, character varying, integer[], integer[]);
CREATE OR REPLACE FUNCTION public.get_reorder_forecast_data(
    IN order_date character varying,
    IN order_arrival_date character varying,
    IN advance_stock_start_date character varying,
    IN advance_stock_end_date character varying,
    IN product_ids integer[],
    IN warehouse_ids integer[])
  RETURNS TABLE(product_id integer, lead_days_demand_stock double precision, expected_sales_stock double precision) AS
$BODY$
BEGIN
RETURN QUERY
SELECT
        T1.product_id,
        sum(T1.lead_days_demand_stock) as lead_days_demand_stock,
        sum(T1.expected_sales_stock) as expected_sales_stock
    FROM (
    ---- get lead_days_demand_stock
    SELECT
        f.product_id,
        fp.id as fiscal_period_id,
        f.average_daily_forecast_qty,
        COUNT(dt.*) as days,
        (f.average_daily_forecast_qty * COUNT(dt.*)) lead_days_demand_stock,
        0.0 as expected_sales_stock
    FROM
        generate_series(order_date::DATE,order_arrival_date::DATE,interval '1 DAY' ) as dt,
        forecast_product_sale f
        inner join reorder_fiscalperiod fp on fp.id=f.period_id
    WHERE
        extract(YEAR from fp.fpstartdate) = extract(YEAR from date_trunc('month',dt)) and
        extract(MONTH from fp.fpstartdate) = extract(MONTH from date_trunc('month',dt))
    --product dynamic condition
    and 1 = case when array_length(product_ids,1) >= 1 then
    case when f.product_id = ANY(product_ids) then 1 else 0 end
    else 1 end
    --warehouse dynamic condition
    and 1 = case when array_length(warehouse_ids,1) >= 1 then
    case when f.warehouse_id = ANY(warehouse_ids) then 1 else 0 end
    else 1 end
    group by
        f.product_id,f.average_daily_forecast_qty,fiscal_period_id
    UNION ALL
    --- get expected_sales_stock
    SELECT
        f.product_id,
        fp.id as fiscal_period_id,
        f.average_daily_forecast_qty,
        COUNT(dt.*) as days,
        0.0 as lead_days_demand_stock,
        (f.average_daily_forecast_qty * COUNT(dt.*)) expected_sales_stock
    FROM
        generate_series(advance_stock_start_date::DATE,advance_stock_end_date::DATE,interval '1 DAY' ) as dt,
        forecast_product_sale f
        inner join reorder_fiscalperiod fp on fp.id=f.period_id
    WHERE
        extract(YEAR from fp.fpstartdate) = extract(YEAR from date_trunc('month',dt)) and
        extract(MONTH from fp.fpstartdate) = extract(MONTH from date_trunc('month',dt))
    --product dynamic condition
    and 1 = case when array_length(product_ids,1) >= 1 then
    case when f.product_id = ANY(product_ids) then 1 else 0 end
    else 1 end
    --warehouse dynamic condition
    and 1 = case when array_length(warehouse_ids,1) >= 1 then
    case when f.warehouse_id = ANY(warehouse_ids) then 1 else 0 end
    else 1 end
    group by
        f.product_id,f.average_daily_forecast_qty,fiscal_period_id
    ) T1
    group by T1.product_id
    order by T1.product_id;

END; $BODY$
LANGUAGE plpgsql VOLATILE
COST 100
ROWS 1000;