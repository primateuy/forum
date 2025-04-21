DROP FUNCTION IF EXISTS public.get_reorder_non_product_forecast(integer, character varying, character varying, integer, integer, integer[], integer[]);
CREATE OR REPLACE FUNCTION public.get_reorder_non_product_forecast(
    user_id integer,
    start_date character varying,
    end_date character varying,
    reorder_id integer,
    procurement_id integer,
    product_ids integer[],
    warehouse_ids integer[])
  RETURNS boolean AS
$BODY$
DECLARE
    fiscal_period_ids integer[] := (SELECT ARRAY(
                                            SELECT
                                                id
                                            FROM
                                                generate_series(start_date::DATE,end_date::DATE,interval '1 DAY') as dt,
                                                reorder_fiscalperiod
                                            WHERE
                                                extract(YEAR from fpstartdate) = extract(YEAR from date_trunc('month',dt)) and
                                                extract(MONTH from fpstartdate) = extract(MONTH from date_trunc('month',dt))
                                            group by id));
    return_value BOOLEAN := False;
    BEGIN
        delete from advance_reorder_non_product_forecast where reorder_process_id=reorder_id or procurement_process_id=procurement_id;

        INSERT INTO advance_reorder_non_product_forecast(create_uid,create_date,write_uid,write_date,period_id,product_id,warehouse_id,reorder_process_id,procurement_process_id)
        Select
            user_id,
            NOW() at time zone 'UTC',
            user_id,
            NOW() at time zone 'UTC',
            T.period_id,
            T.product_id,
            T.warehouse_id,
            reorder_id,
            procurement_id
        from
        (SELECT
            fp.id as period_id,
            prod.id as product_id,
            ware.id as warehouse_id
        FROM
            reorder_fiscalperiod fp,
            product_product prod,
            stock_warehouse ware
        WHERE
            fp.id = ANY(fiscal_period_ids) and
            prod.id = ANY(product_ids) and
            ware.id = ANY(warehouse_ids)
        group by fp.id,prod.id,ware.id
        EXCEPT
        select
            period_id, product_id, warehouse_id
        from
            forecast_product_sale
        where
            period_id = ANY(fiscal_period_ids) and
            product_id = ANY(product_ids) and
            warehouse_id = ANY(warehouse_ids)
        group by period_id, product_id, warehouse_id
        order by product_id, warehouse_id,period_id)T;

        IF EXISTS(select * from advance_reorder_non_product_forecast where reorder_process_id=reorder_id or procurement_process_id=procurement_id) THEN
            return_value := True;
        END IF;

    RETURN return_value;
    END;
$BODY$
  LANGUAGE plpgsql VOLATILE
  COST 100;