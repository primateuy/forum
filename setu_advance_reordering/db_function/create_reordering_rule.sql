DROP FUNCTION IF EXISTS public.create_reordering_rule(integer[], integer[], integer[], integer[], integer);
DROP FUNCTION IF EXISTS public.create_reordering_rule(integer[], integer[], integer[], integer[], integer, character varying, integer);
CREATE OR REPLACE FUNCTION public.create_reordering_rule(
    company_ids integer[],
    product_ids integer[],
    category_ids integer[],
    warehouse_ids integer[],
    uid integer,
    location_type character varying,
    specific_location_id integer)
    RETURNS TABLE(id integer)
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
    AS $BODY$
    Declare avg_sale_calc_base Text := (select value from ir_config_parameter where key = 'setu_advance_reordering.average_sale_calculation_base');
        id_list integer[];
        max_id integer := (select max(op.id) from stock_warehouse_orderpoint op);
        final_max_id integer := (CASE WHEN max_id is not null and max_id > 0 then max_id else 0 end);
    BEGIN
        insert into stock_warehouse_orderpoint
        (name, company_id, product_id, warehouse_id, location_id, average_sale_calculation_base,
        product_min_qty, product_max_qty, qty_multiple,
        create_uid, create_date, write_uid, write_date, active, trigger, document_creation_option, vendor_selection_strategy)
        Select 	(coalesce(seq.prefix, 'OP/') || nextval('stock_warehouse_orderpoint_id_seq')::Text)::character varying,
            prod_ware.company_id, product_id, warehouse_id, location_id, avg_sale_calc_base, 0, 0, 1,
            uid, now()::date, uid, now()::date, True, 'auto', 'od_default', 'NA' from
        (
            Select prod.id as product_id, ware.id as warehouse_id,
            case when location_type = 'lot_stock' then ware.lot_stock_id
            else case when location_type = 'input' then ware.wh_input_stock_loc_id else specific_location_id end end as location_id,
            ware.company_id
            from product_product prod left join product_template tmpl on tmpl.id = prod.product_tmpl_id, stock_warehouse ware
            where tmpl.type = 'product'
            and tmpl.purchase_ok = true
            and prod.active = true and tmpl.active = true
            and 1 = case when array_length(product_ids,1) >= 1 then
                        case when prod.id = ANY(product_ids) then 1 else 0 end
                        else 1 end
                    --warehouse dynamic condition
                    and 1 = case when array_length(warehouse_ids,1) >= 1 then
                        case when ware.id = ANY(warehouse_ids) then 1 else 0 end
                        else 1 end

            EXCEPT

            select product_id, warehouse_id, location_id, company_id from stock_warehouse_orderpoint
            where 1 = case when array_length(product_ids,1) >= 1 then
                case when product_id = ANY(product_ids) then 1 else 0 end
                else 1 end
            --warehouse dynamic condition
            and 1 = case when array_length(warehouse_ids,1) >= 1 then
                case when warehouse_id = ANY(warehouse_ids) then 1 else 0 end
                else 1 end
        )prod_ware
            Inner Join stock_warehouse wh on wh.id = prod_ware.warehouse_id
            Left Join ir_sequence seq on seq.company_id = wh.company_id and seq.code like '%orderpoint%';
        RETURN QUERY
        select op.id from stock_warehouse_orderpoint op where op.id > final_max_id;
    END;
$BODY$;

