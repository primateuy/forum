/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { useBarcodeReader } from "@point_of_sale/app/barcode/barcode_reader_hook";
import { patch } from "@web/core/utils/patch";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { SalespersonPopup } from "@pw_pos_salesperson_emp/input_popups/salesperson_popup";


patch(ProductScreen.prototype, {
    setup() {
        super.setup(...arguments);
    },
    async changeEmployee(orderline) {
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
            orderline.set_line_emp(selectedEmp);
        }
    },
    removeEmployee(orderline) {
        orderline.remove_sale_person()
    }
});
