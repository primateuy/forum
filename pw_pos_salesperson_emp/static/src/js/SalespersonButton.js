/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { useService } from "@web/core/utils/hooks";
import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { Component } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { SalespersonPopup } from "@pw_pos_salesperson_emp/input_popups/salesperson_popup";


export class SalespersonButton extends Component {
    static template = "pw_pos_salesperson.SalespersonButton";

    setup() {
        this.pos = usePos();
        this.popup = useService("popup");
    }
    async click() {
        const selectionList = this.pos.employees.map(user => ({
            id: user.id,
            label: user.name,
            item: user,
        }));
        const { confirmed, payload: selectedEmp } = await this.popup.add(
            SalespersonPopup,
            {
                title: _t("Select Salesperson"),
                list: selectionList,
            }
        );
        if (confirmed) {
            const order = this.pos.get_order();
            const orderLines = order.get_orderlines();
            for (const line of orderLines) {
                line.set_line_emp(selectedEmp);
            }
        }
    }
}

ProductScreen.addControlButton({
    component: SalespersonButton,
    condition: function () {
        return this.pos.config.allow_salesperson;
    },
});
