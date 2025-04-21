DROP FUNCTION IF EXISTS public.update_product_sales_history(integer[], integer[], integer[], integer[], date, date, integer);
--DROP FUNCTION IF EXISTS public.update_product_sales_history(integer[], integer[], integer[], integer[], integer[], date, date, integer);
CREATE OR REPLACE FUNCTION public.update_product_sales_history(
    company_ids integer[],
    product_ids integer[],
    category_ids integer[],
    warehouse_ids integer[],
	--location_ids integer[]
    date_start date,
    date_end date,
    uid integer)
  RETURNS void AS
$BODY$
    BEGIN
		with row_datas as (Select * from get_product_sales_history_data(company_ids,product_ids,category_ids,warehouse_ids,date_start,date_end)),
		i1 as
			(UPDATE product_sales_history as psh
				SET sales_qty = rd.sales_qty,
				average_daily_sale = rd.ads,
				max_daily_sale_qty = rd.max_daily_sale,
				min_daily_sale_qty = rd.min_daily_sale,
				actual_sales_qty=rd.t_sales_qty,
				actual_sales_return_qty=rd.t_sales_return_qty,
				total_orders = rd.total_orders,
				write_date = now()::date,
				write_uid = uid
				--, orderpoint_id = swo.id
			from
				row_datas rd
			WHERE
				psh.product_id = rd.product_id
				and psh.warehouse_id = rd.warehouse_id
				--and psh.location_id = rd.location_id
				and  psh.start_date = date_start and psh.end_date = date_end)

			Insert into product_sales_history
                    (product_id, warehouse_id, orderpoint_id,sales_qty, average_daily_sale, max_daily_sale_qty,
                     min_daily_sale_qty, start_date, end_date,duration, total_orders, create_date,
					 write_date, create_uid, write_uid,actual_sales_qty,actual_sales_return_qty)
                    Select
						rd.product_id,
						rd.warehouse_id,
						rd.orderpoint_id,
						rd.sales_qty,
						rd.ads, rd.max_daily_sale,
                    	rd.min_daily_sale,
						date_start,
						date_end,
						(date_end-date_start)+1 ,
						rd.total_orders,
						now()::date, now()::date, uid, uid,
						rd.t_sales_qty,rd.t_sales_return_qty
                    From(select op.id as orderpoint_id,row_datas.* from row_datas
				                join stock_warehouse_orderpoint op on op.product_id = row_datas.product_id and op.warehouse_id = row_datas.warehouse_id
				                left join product_sales_history sh on sh.orderpoint_id = op.id
				                and sh.start_date = date_start and sh.end_date = date_end
			    	            where sh.id is null
                                 )rd;
																	--and op.location_id = rd.location_id;

	END;
$BODY$
LANGUAGE plpgsql VOLATILE
COST 100;