DROP FUNCTION IF EXISTS public.update_actual_sales(integer[], integer[], integer, date, date);
CREATE OR REPLACE FUNCTION public.update_actual_sales(
	product_ids integer[],
	warehouse_ids integer[],
	period_id integer,
	start_date date,
	end_date date)
    RETURNS void
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
AS $BODY$
DECLARE
    period integer := period_id;
BEGIN
    --RAISE INFO 'Period: %', period_id;
    update forecast_product_sale fps
        set actual_sale_qty = T.product_qty
    from (
            select D.product_id, D.warehouse_id, sum(D.product_qty) as product_qty from
            (
                Select S.product_id,S.warehouse_id,S.product_qty as product_qty from get_stock_data(null,product_ids,null,warehouse_ids,'sales',start_date,end_date)S
                UNION ALL
                Select SR.product_id,SR.warehouse_id,SR.product_qty * -1 as product_qty from get_stock_data(null,product_ids,null,warehouse_ids,'sales_return',start_date,end_date)SR
            )D group by D.product_id, D.warehouse_id
    ) T
    where fps.product_id = T.product_id and fps.warehouse_id = T.warehouse_id and fps.period_id = period;
END;
$BODY$;