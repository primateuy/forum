DROP FUNCTION IF EXISTS public.update_product_purchase_history(integer[], integer[], date, date, integer);
CREATE OR REPLACE FUNCTION public.update_product_purchase_history(
    product_ids integer[],
    warehouse_ids integer[],
    date_start date,
    date_end date,
    uid integer)
  RETURNS void AS
$BODY$
    BEGIN
    with row_datas as (select * from get_purchase_data_form_stock_move(product_ids,warehouse_ids,date_start,date_end,uid)),
		i1 as
			(
            UPDATE product_purchase_history as pph
                SET po_qty = rd.qty_ordered,
                currency_id = rd.currency_id,
                purchase_price = rd.price_unit,
                po_date = rd.date_order,
                lead_time = rd.lead_time,
                write_date = rd.write_date,
                write_uid = rd.write_uid
            from row_datas rd
            WHERE
                pph.product_id = rd.product_id
                and pph.warehouse_id = rd.warehouse_id
                and pph.partner_id = rd.partner_id
                and pph.purchase_id = rd.order_id
                and pph.orderpoint_id = rd.orderpoint_id)

			Insert into product_purchase_history
                    (
                        product_id, warehouse_id, partner_id, orderpoint_id, purchase_id, po_qty, currency_id, purchase_price, po_date, lead_time,
                        create_uid, create_date, write_uid, write_date
                    )
                    select rd.product_id, rd.warehouse_id, rd.partner_id, rd.orderpoint_id, rd.order_id, rd.qty_ordered, rd.currency_id, rd.price_unit, rd.date_order, rd.lead_time,
                        rd.create_uid, rd.create_date, rd.write_uid, rd.write_date
                    From
						(select
	                            row_datas.* from product_purchase_history pph
				                        right join row_datas on pph.product_id = row_datas.product_id
										and pph.warehouse_id = row_datas.warehouse_id
										and pph.orderpoint_id = row_datas.orderpoint_id
										and pph.purchase_id = row_datas.order_id
				                where pph.id is null
                        )rd;
    END;
$BODY$
  LANGUAGE plpgsql VOLATILE
  COST 100;
