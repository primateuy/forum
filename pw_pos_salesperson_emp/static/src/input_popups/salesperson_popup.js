/** @odoo-module */

import { AbstractAwaitablePopup } from "@point_of_sale/app/popup/abstract_awaitable_popup";
import { _t } from "@web/core/l10n/translation";
import { useState } from "@odoo/owl";

export class SalespersonPopup extends AbstractAwaitablePopup {
    static template = "pw_pos_salesperson_emp.SalespersonPopup";
    static defaultProps = {
        cancelText: _t("Discard"),
        confirmText: _t("Add"),
        title: _t("Select"),
        body: "",
        list: [],
        confirmKey: false,
    };
    setup() {
        super.setup();
        this.state = useState({ selectedId: this.props.list.find((item) => item.isSelected) });
    }

    /**
     * Leyenda del campo de selección de vendedor en el popup (traducible vía i18n).
     */
    get salespersonFieldLabel() {
        return _t("Salesperson:");
    }
    async onChangeSalesperson(emp_name) {
        const selected_emp = this.props.list.find((item) => item.label === emp_name);
        if (selected_emp) {
            this.selectedEmp = selected_emp;
        }
    }
    selectItem(itemId) {
        this.state.selectedId = itemId;
        this.confirm();
    }
    /**
     * We send as payload of the response the selected item.
     *
     * @override
     */
    getPayload() {
        return this.selectedEmp && this.selectedEmp.item;
    }
}
