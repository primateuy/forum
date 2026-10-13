/** @odoo-module **/

/**
 * «Ordenar» con «seleccionar todo» manda el DOMINIO de la lista, no los ids.
 *
 * El core pide los ids seleccionados (`getSelectedResIds`), que con la selección por
 * dominio se cortan en 20.000 y además viajan todos al servidor. Con el dominio, el
 * servidor arma el proceso en segundo plano con un solo INSERT … SELECT, sea cual sea
 * el tamaño. Con una selección a mano se sigue el camino del core.
 */

import { patch } from "@web/core/utils/patch";
import { StockOrderpointListController } from "@stock/views/stock_orderpoint_list_controller";

patch(StockOrderpointListController.prototype, {
    async onClickOrder(force_to_max) {
        if (!this.model.root.isDomainSelected) {
            return super.onClickOrder(force_to_max);
        }
        const action = await this.model.orm.call(
            this.props.resModel, "forum_reponer_dominio", [this.model.root.domain],
            { context: this.props.context, force_to_max }
        );
        if (action) {
            await this.actionService.doAction(action);
        }
        return this.actionService.doAction("stock.action_replenishment", {
            stackPosition: "replaceCurrentAction",
        });
    },
});
