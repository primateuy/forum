/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { useBarcodeReader } from "@point_of_sale/app/barcode/barcode_reader_hook";
import { patch } from "@web/core/utils/patch";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";


patch(ProductScreen.prototype, {
    setup() {
        super.setup(...arguments);
    },
    async changeUser(orderline) {
        const selectionList = this.pos.user.map(user => ({
            id: user.id,
            label: user.name,
            item: user,
        }));
        const { confirmed, payload: selectedUser } = await this.popup.add(
            SelectionPopup,
            {
                title: _t("Select Salesperson"),
                list: selectionList,
            }
        );
        if (confirmed) {
            orderline.set_line_user(selectedUser);
        }
    },
    removeUser(orderline) {
        orderline.remove_sale_person()
    }
});
