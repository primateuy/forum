DROP FUNCTION IF EXISTS public.get_purchase_data_form_stock_move(integer[], integer[], date, date, integer);
CREATE OR REPLACE FUNCTION public.get_purchase_data_form_stock_move(
    product_ids integer[],
    warehouse_ids integer[],
    date_start date,
    date_end date,
    uid integer)
  RETURNS TABLE
  (
    product_id integer,
    warehouse_id integer,
    partner_id integer,
    orderpoint_id integer,
    order_id integer,
    currency_id integer,
    price_unit numeric,
    date_order timestamp without time zone,
    lead_time numeric,
    create_uid integer,
    create_date date,
    write_uid integer,
    write_date  date,
    qty_ordered numeric
   ) AS
$BODY$
    DECLARE
        temprow record;
        tr_date_start timestamp without time zone := (date_start || ' 00:00:00')::timestamp without time zone;
        tr_date_end timestamp without time zone:= (date_end || ' 23:59:59')::timestamp without time zone;
    BEGIN
        Return Query
        Select
            T.product_id as product_id,
            T.warehouse_id as warehouse_id,
            T.partner_id as partner_id,
            T.orderpoint_id as orderpoint_id,
            T.order_id AS order_id,
            T.currency_id as currency_id,
            T.price_unit as price_unit,
            T.date_order as date_order,
            (T.done_date::date- T.date_order::date)+1::numeric as lead_time,
            uid as create_uid,
            now()::date as create_date,
            uid as write_uid,
            now()::date as write_date,
            coalesce(sum(T.product_qty),0) as qty_ordered
    From
    (
        Select
            po.partner_id as partner_id,
            op.id as orderpoint_id,
            po.id as order_id,
            po.currency_id as currency_id,
            l.price_unit as price_unit,
            move.date as done_date,
            po.date_order,
            move.company_id,
            move.product_id as product_id,
            case when source.usage = 'internal' then
                source_warehouse.id else  dest_warehouse.id end as warehouse_id,
            --case when source.usage = 'internal' then
                --move.product_uom_qty * -1 else
            move.product_uom_qty as product_qty

        From
            stock_move move
                Inner Join purchase_order_line l ON l.id = move.purchase_line_id
                Inner JOIN purchase_order po ON l.order_id = po.id
                Inner JOIN stock_picking_type spt ON spt.id = po.picking_type_id
                Inner Join stock_location source on source.id = move.location_id
                Inner Join stock_location dest on dest.id = move.location_dest_id
                Inner Join res_company cmp on cmp.id = move.company_id
                Inner Join product_product prod on prod.id = move.product_id
                Inner Join product_template tmpl on tmpl.id = prod.product_tmpl_id
                Inner Join product_category cat on cat.id = tmpl.categ_id
                Inner Join stock_warehouse_orderpoint op on op.product_id = l.product_id and op.warehouse_id = spt.warehouse_id
                Left Join stock_warehouse source_warehouse ON source.parent_path::text ~~ concat('%/', source_warehouse.view_location_id, '/%')
                Left Join stock_warehouse dest_warehouse ON dest.parent_path::text ~~ concat('%/', dest_warehouse.view_location_id, '/%')
        where prod.active = true and tmpl.active = true
        and move.date::date >= tr_date_start and move.date::date <= tr_date_end
        and move.state = 'done'
        and tmpl.type = 'product'
        and dest.usage = 'internal'

        and 1 = case when array_length(product_ids,1) >= 1 then
            case when move.product_id = ANY(product_ids) then 1 else 0 end
            else 1 end
        --warehouse dynamic condition
        and 1 = case when array_length(warehouse_ids,1) >= 1 then
            case when source.usage = 'internal' then
                case when source_warehouse.id = ANY(warehouse_ids) then 1 else 0 end
            else
                case when dest_warehouse.id = ANY(warehouse_ids) then 1 else 0 end
            end
        else 1 end
    )T
    group by  T.partner_id, T.product_id, T.price_unit,T.date_order, T.done_date, T.currency_id,
                             T.order_id, T.warehouse_id, T.orderpoint_id;
    END;
$BODY$
  LANGUAGE plpgsql VOLATILE
  COST 100;
