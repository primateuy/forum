DROP FUNCTION IF EXISTS public.get_product_sales_history_data(integer[], integer[], integer[], integer[], date, date);
CREATE OR REPLACE FUNCTION public.get_product_sales_history_data(
    IN company_ids integer[],
    IN product_ids integer[],
    IN category_ids integer[],
    IN warehouse_ids integer[],
    IN start_date date,
    IN end_date date)
  RETURNS TABLE(company_id integer, product_id integer, product_category_id integer, warehouse_id integer, sales_qty numeric, total_orders numeric, ads numeric, max_daily_sale numeric, min_daily_sale numeric, t_sales_qty numeric, t_sales_return_qty numeric) AS
$BODY$
    DECLARE
        end_date date:= (case when CURRENT_DATE <= end_date::date and CURRENT_DATE >=start_date::date then CURRENT_DATE else end_date END);
        day_difference integer := ((end_date::Date-start_date::Date)+1);
        tr_start_date timestamp without time zone := (start_date || ' 00:00:00')::timestamp without time zone;
        tr_end_date timestamp without time zone:= (end_date || ' 23:59:59')::timestamp without time zone;
        pos_id integer:= (select id from ir_module_module where name='point_of_sale' and state='installed');
        pos_installed char := (case when pos_id is not null and pos_id > 0 then 'Y' else 'N' end);
    BEGIN
    IF pos_installed = 'N' then
        Return Query
            Select
                sd.cmp_id,
                sd.p_id,
                sd.categ_id,
                sd.wh_id,
                sum(sd.total_sales) - sum(sd.total_return_qty) as total_sales,
                sum(sd.total_orders) as total_orders,
                case when (sum(sd.total_sales) - sum(sd.total_return_qty)) <= 0 then 0 else
                round((sum(sd.total_sales) - sum(sd.total_return_qty)) /day_difference,2) end as ads,
                max(sd.total_sales) max_daily_sale,
                --min(sd.total_sales) min_daily_sale,
                MIN(NULLIF(sd.total_sales, 0)) min_daily_sale,
                sum(sd.total_sales) as t_sales_qty,
                sum(sd.total_return_qty) as t_sales_return_qty
            From (
                    Select
                        cmp_id,
                        p_id,
                        categ_id,
                        wh_id,
                        T.order_date,
                        sum(T.sales_qty) as total_sales,
                        sum(T.sales_return_qty) as total_return_qty,
                        count(T.order_id) as total_orders
                        --,sum(T.sales_qty) as ads, sum(T.sales_qty) max_daily_sale,
                        --min(T.sales_qty) min_daily_sale
                    From(Select
                            foo.cmp_id,
                            foo.p_id,
                            foo.categ_id,
                            foo.wh_id,
                            sum(Round(foo.sales_qty,2)) AS sales_qty,
                            sum(Round(foo.sales_return_qty,2)) AS sales_return_qty,
                            foo.order_id,
                            foo.order_date
                        From (Select
                                    move.company_id as cmp_id,
                                    move.product_id as p_id,
                                    tmpl.categ_id,
                                    case when source.usage = 'internal' then
                                            source_warehouse.id else  dest_warehouse.id end as wh_id,
                                    case when source.usage = 'internal' then so.id else null::integer end as order_id,
                                    --so.id as order_id,
                                    move.date::date as order_date,
                                    case when source.usage = 'internal' then
                                            move.product_uom_qty else 0 end as sales_qty,
                                    case when source.usage = 'customer' then
                                            move.product_uom_qty else 0 end as sales_return_qty

                              From
                                    stock_move move
                                    Inner Join sale_order_line sol on sol.id = move.sale_line_id
                                    Inner join sale_order so on so.id = sol.order_id
                                    Inner Join stock_location source on source.id = move.location_id
                                    Inner Join stock_location dest on dest.id = move.location_dest_id
                                    Inner Join res_company cmp on cmp.id = move.company_id
                                    Inner Join product_product prod on prod.id = move.product_id
                                    Inner Join product_template tmpl on tmpl.id = prod.product_tmpl_id
                                    Inner Join product_category cat on cat.id = tmpl.categ_id
                                    Left Join stock_warehouse source_warehouse ON source.parent_path::text ~~ concat('%/', source_warehouse.view_location_id, '/%')
                                    Left Join stock_warehouse dest_warehouse ON dest.parent_path::text ~~ concat('%/', dest_warehouse.view_location_id, '/%')
                              where prod.active = true and tmpl.active = true
                              and move.date::date >= tr_start_date and move.date::date <= tr_end_date
                              and move.state = 'done'
                              and tmpl.type = 'product'
                              and 1 = case when array_length(company_ids,1) >= 1 then
                                        case when move.company_id = ANY(company_ids) then 1 else 0 end
                                      else 1 end
                                --product dynamic condition
                              and 1 = case when array_length(product_ids,1) >= 1 then
                                          case when move.product_id = ANY(product_ids) then 1 else 0 end
                                      else 1 end
                                --category dynamic condition
                              and 1 = case when array_length(category_ids,1) >= 1 then
                                          case when tmpl.categ_id = ANY(category_ids) then 1 else 0 end
                                      else 1 end
                                --warehouse dynamic condition
                              and 1 = case when array_length(warehouse_ids,1) >= 1 then
                                          case when source.usage = 'internal' then
                                              case when source_warehouse.id = ANY(warehouse_ids) then 1 else 0 end
                                          else
                                              case when dest_warehouse.id = ANY(warehouse_ids) then 1 else 0 end
                                          end
                                      else 1 end

                              Union All

                              SELECT
                                wh.company_id as cmp_id,
                                pro.id as p_id,
                                pt.categ_id,
                                wh.id as wh_id,
                                null::integer as order_id,
                                start_date::date as order_date,
                                0 AS sales_qty,
                                0 AS sales_return_qty
                              FROM product_product pro, product_template pt, stock_warehouse wh
                                Where pro.product_tmpl_id = pt.id
                                and 1 = case when array_length(company_ids,1) >= 1 then
                                case when wh.company_id = ANY(company_ids) then 1 else 0 end
                                else 1 end
                                --product dynamic condition
                                and 1 = case when array_length(product_ids,1) >= 1 then
                                case when pro.id = ANY(product_ids) then 1 else 0 end
                                else 1 end
                                --category dynamic condition
                                and 1 = case when array_length(category_ids,1) >= 1 then
                                case when pt.categ_id = ANY(category_ids) then 1 else 0 end
                                else 1 end
                                --warehouse dynamic condition
                                and 1 = case when array_length(warehouse_ids,1) >= 1 then
                                case when wh.id = ANY(warehouse_ids) then 1 else 0 end
                                else 1 end
                              )foo
                              group by foo.cmp_id, foo.p_id, foo.order_id, foo.order_date,foo.categ_id,foo.wh_id
                    )T
    -- 			    group by cmp_id, cmp_name, p_id, prod_name, categ_id, cat_name, wh_id, ware_name,  T.order_date
                    group by cmp_id, p_id, categ_id, wh_id,  T.order_date
            )sd
-- 			group by cmp_id, cmp_name, p_id, prod_name, categ_id, cat_name, wh_id, ware_name;
            group by cmp_id, p_id, categ_id, wh_id;
        ELSE
         Return Query
            Select
                sd.cmp_id,
                sd.p_id,
                sd.categ_id,
                sd.wh_id,
                sum(sd.total_sales) - sum(sd.total_return_qty) as total_sales,
                sum(sd.total_orders) as total_orders,
                case when (sum(sd.total_sales) - sum(sd.total_return_qty)) <= 0 then 0 else
                round((sum(sd.total_sales) - sum(sd.total_return_qty)) /day_difference,2) end as ads,
                max(sd.total_sales) max_daily_sale,
                --min(sd.total_sales) min_daily_sale,
                MIN(NULLIF(sd.total_sales, 0)) min_daily_sale,
                sum(sd.total_sales) as t_sales_qty,
                sum(sd.total_return_qty) as t_sales_return_qty
            From (Select
                    cmp_id,
                    p_id,
                    categ_id,
                    wh_id,
                    T.order_date,
                    sum(T.sales_qty) as total_sales,
                    sum(T.sales_return_qty) as total_return_qty,
                    count(T.order_id)+count(T.pos_order_id) as total_orders
                    --,sum(T.sales_qty) as ads, sum(T.sales_qty) max_daily_sale,
                    --min(T.sales_qty) min_daily_sale
                  From(Select
                            foo.cmp_id,
                            foo.p_id,
                            foo.categ_id,
                            foo.wh_id,
                            sum(Round(foo.sales_qty,2)) AS sales_qty,
                            sum(Round(foo.sales_return_qty,2)) AS sales_return_qty,
                            foo.order_id,
                            foo.pos_order_id,
                            foo.order_date
                       From (Select
                                move.company_id as cmp_id,
                                move.product_id as p_id,
                                tmpl.categ_id,
                                case when source.usage = 'internal' then
                                        source_warehouse.id else  dest_warehouse.id end as wh_id,
                                case when source.usage = 'internal' then so.id else null::integer end as order_id,
                                --so.id as order_id,
                                null::integer as pos_order_id,
                                move.date::date as order_date,
                                case when source.usage = 'internal' then
                                      move.product_uom_qty else 0 end as sales_qty,
                                case when source.usage = 'customer' then
                                      move.product_uom_qty else 0 end as sales_return_qty
                             From
                                stock_move move
                                Inner Join sale_order_line sol on sol.id = move.sale_line_id
                                Inner join sale_order so on so.id = sol.order_id
                                Inner Join stock_location source on source.id = move.location_id
                                Inner Join stock_location dest on dest.id = move.location_dest_id
                                Inner Join res_company cmp on cmp.id = move.company_id
                                Inner Join product_product prod on prod.id = move.product_id
                                Inner Join product_template tmpl on tmpl.id = prod.product_tmpl_id
                                Inner Join product_category cat on cat.id = tmpl.categ_id
                                Left Join stock_warehouse source_warehouse ON source.parent_path::text ~~ concat('%/', source_warehouse.view_location_id, '/%')
                                Left Join stock_warehouse dest_warehouse ON dest.parent_path::text ~~ concat('%/', dest_warehouse.view_location_id, '/%')
                            where prod.active = true and tmpl.active = true
                            and move.date::date >= tr_start_date and move.date::date <= tr_end_date
                            and move.state = 'done'
                            and tmpl.type = 'product'
                            and 1 = case when array_length(company_ids,1) >= 1 then
                            case when move.company_id = ANY(company_ids) then 1 else 0 end
                            else 1 end
                            --product dynamic condition
                            and 1 = case when array_length(product_ids,1) >= 1 then
                            case when move.product_id = ANY(product_ids) then 1 else 0 end
                            else 1 end
                            --category dynamic condition
                            and 1 = case when array_length(category_ids,1) >= 1 then
                            case when tmpl.categ_id = ANY(category_ids) then 1 else 0 end
                            else 1 end
                            --warehouse dynamic condition
                            and 1 = case when array_length(warehouse_ids,1) >= 1 then
                                        case when source.usage = 'internal' then
                                            case when source_warehouse.id = ANY(warehouse_ids) then 1 else 0 end
                                        else
                                            case when dest_warehouse.id = ANY(warehouse_ids) then 1 else 0 end
                                        end
                                    else 1 end

                       Union All

                       select
                            pso.company_id as cmp_id,
                            pol.product_id as p_id,
                            pt.categ_id,
                            spt.warehouse_id as wh_id,
                            null::integer as order_id,
                            case when pol.qty > 0 then pol.order_id else null::integer end as pos_order_id,
                            pso.date_order::date as order_date,
                            case when pol.qty > 0 then
                                    pol.qty else 0 end as sales_qty,
                            case when pol.qty < 0 then
                                    pol.qty*-1 else 0 end as sales_return_qty

                       from
                            pos_order_line pol
                            join pos_order pso on pso.id = pol.order_id
                            join pos_session ps on ps.id = pso.session_id
                            join pos_config pc on pc.id = ps.config_id
                            join stock_picking_type spt on spt.id = pc.picking_type_id
                            Join product_product pro ON pol.product_id = pro.id
                            Join product_template pt ON pro.product_tmpl_id = pt.id
                            WHERE pso.state::text = ANY (ARRAY['paid'::character varying::text,'invoiced'::character varying::text, 'done'::character varying::text])
                            and (coalesce(pro.capping_qty,0) = 0.0 or pol.qty <= coalesce(pro.capping_qty,0))
                            and pso.date_order::date >= tr_start_date and pso.date_order::date <= tr_end_date
                            --company dynamic condition
                            and 1 = case when array_length(company_ids,1) >= 1 then
                            case when pso.company_id = ANY(company_ids) then 1 else 0 end
                            else 1 end
                            --product dynamic condition
                            and 1 = case when array_length(product_ids,1) >= 1 then
                            case when pol.product_id = ANY(product_ids) then 1 else 0 end
                            else 1 end
                            --category dynamic condition
                            and 1 = case when array_length(category_ids,1) >= 1 then
                            case when pt.categ_id = ANY(category_ids) then 1 else 0 end
                            else 1 end
                            --warehouse dynamic condition
                            and 1 = case when array_length(warehouse_ids,1) >= 1 then
                            case when spt.warehouse_id = ANY(warehouse_ids) then 1 else 0 end
                            else 1 end

                       Union All

                       SELECT
                            wh.company_id as cmp_id,
                            pro.id as p_id,
                            pt.categ_id,
                            wh.id as wh_id,
                            null::integer as order_id,
                            null::integer as pos_order_id,
                            start_date::date as order_date,
                            0 as sales_qty,
                            0 as sales_return_qty
                       FROM product_product pro, product_template pt, stock_warehouse wh
                       Where pro.product_tmpl_id = pt.id
                            and 1 = case when array_length(company_ids,1) >= 1 then
                                        case when wh.company_id = ANY(company_ids) then 1 else 0 end
                                    else 1 end
                            --product dynamic condition
                            and 1 = case when array_length(product_ids,1) >= 1 then
                                        case when pro.id = ANY(product_ids) then 1 else 0 end
                                    else 1 end
                            --category dynamic condition
                            and 1 = case when array_length(category_ids,1) >= 1 then
                                        case when pt.categ_id = ANY(category_ids) then 1 else 0 end
                                    else 1 end
                            --warehouse dynamic condition
                            and 1 = case when array_length(warehouse_ids,1) >= 1 then
                                        case when wh.id = ANY(warehouse_ids) then 1 else 0 end
                                    else 1 end
                  )foo
                    group by foo.cmp_id, foo.p_id, foo.order_id, foo.order_date,foo.categ_id,foo.wh_id,foo.pos_order_id
            )T
                group by cmp_id, p_id, categ_id, wh_id,  T.order_date
         )sd
            group by cmp_id, p_id, categ_id, wh_id;
           END IF;

        END;

$BODY$
LANGUAGE plpgsql VOLATILE
COST 100
ROWS 1000;
