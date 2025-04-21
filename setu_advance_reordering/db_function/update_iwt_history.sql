DROP FUNCTION IF EXISTS public.update_product_iwt_history(integer[], integer[], date, date, integer);
CREATE OR REPLACE FUNCTION public.update_product_iwt_history(
product_ids integer[],
warehouse_ids integer[],
--location_ids integer[]
date_start date,
date_end date,
uid integer)
RETURNS void AS
$BODY$
	BEGIN
		with row_datas as (Select
                                move.product_id as p_id,
                                move.create_date::date as date,
                                dest_warehouse.id as warehouse_id,
                                move.picking_id,
                                op.id as orderpoint_id,
                                sum(move.product_uom_qty) AS qty,
                                (move.date::date - move.create_date::date)+1 as lead_time

                            From
                                stock_move move
                                --inner join stock_picking sp on sp.id = move.picking_id
                                Inner Join stock_location source on source.id = move.location_id
                                Inner Join stock_location dest on dest.id = move.location_dest_id
                                Inner Join product_product prod on prod.id = move.product_id
                                Inner Join product_template tmpl on tmpl.id = prod.product_tmpl_id
                                Left Join stock_warehouse source_warehouse ON source.parent_path::text ~~ concat('%/', source_warehouse.view_location_id, '/%')
                                Left Join stock_warehouse dest_warehouse ON dest.parent_path::text ~~ concat('%/', dest_warehouse.view_location_id, '/%')
                                Inner JOIN stock_warehouse_orderpoint op on op.product_id = move.product_id and op.warehouse_id = dest_warehouse.id
                            where prod.active = true and tmpl.active = true
                                    and source.usage in ('transit','internal') and dest.usage = 'internal'
                                    and move.date::date >= date_start and move.date::date <= date_end
                                    and move.state = 'done'
                                    and tmpl.type = 'product'
                                    and 1 = case when array_length(product_ids,1) >= 1 then
                                        case when move.product_id = ANY(product_ids) then 1 else 0 end
                                    else 1 end
                                    --warehouse dynamic condition
                                    and 1 = case when array_length(warehouse_ids,1) >= 1 then
                                        case when dest_warehouse.id = ANY(warehouse_ids) then 1 else 0 end
                                    else 1 end
                                    and 1 = case when source.usage = 'transit' then 1 else
                                        case when source.usage = 'internal' then
                                            case when
                                            (source_warehouse.company_id = dest_warehouse.company_id
                                            and source_warehouse.id != dest_warehouse.id) then 1 else 0 end
                                        else 0 end end
                            group by
                                move.product_id,dest_warehouse.id,move.picking_id,op.id,move.create_date::date,move.date::date

					),i1 as (
							update
								product_iwt_history as pwh
								set date = rd.date,
									qty = rd.qty,
									lead_time = rd.lead_time
							from
								row_datas rd
							WHERE
								pwh.orderpoint_id = rd.orderpoint_id
								and pwh.picking_id = rd.picking_id
								and pwh.product_id = rd.p_id
								and pwh.warehouse_id = rd.warehouse_id
								)
							Insert into product_iwt_history(
								picking_id,product_id,date,qty,warehouse_id,orderpoint_id,lead_time,
								create_date,write_date,create_uid,write_uid
							)
							select row_datas.picking_id,
									row_datas.p_id,
									row_datas.date,
									row_datas.qty,
									row_datas.warehouse_id,
									row_datas.orderpoint_id,
									row_datas.lead_time,
									now()::date,
									now()::date, uid,
									uid
							from product_iwt_history as pih
							right join row_datas on pih.product_id = row_datas.p_id
												and pih.warehouse_id = row_datas.warehouse_id
												and pih.orderpoint_id = row_datas.orderpoint_id
												and pih.picking_id = row_datas.picking_id
							where pih is null;
	END;
$BODY$
LANGUAGE plpgsql VOLATILE
COST 100;
