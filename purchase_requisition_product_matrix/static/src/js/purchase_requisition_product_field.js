/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ProductMatrixDialog } from "@product_matrix/js/product_matrix_dialog";
import { useRecordObserver } from "@web/model/relational_model/utils";
import { Many2OneField, many2OneField } from "@web/views/fields/many2one/many2one_field";

export class PurchaseRequisitionLineProductField extends Many2OneField {
    setup() {
        super.setup();
        this.dialog = useService("dialog");
        this.currentValue = this.value;

        useRecordObserver((record) => {
            if (record.isInEdition && this.value) {
                if (!this.currentValue || this.currentValue[0] !== record.data[this.props.name][0]) {
                    this._onProductTemplateUpdate();
                }
            }
            this.currentValue = record.data[this.props.name];
        });
    }

    get configurationButtonHelp() {
        return _t("Edit Configuration");
    }

    get isConfigurableTemplate() {
        return this.props.record.data.is_configurable_product;
    }

    async _onProductTemplateUpdate() {
        const result = await this.orm.call(
            "product.template",
            "get_single_product_variant",
            [this.props.record.data.product_template_id[0]],
        );
        if (result && result.product_id) {
            if (this.props.record.data.product_id != result.product_id) {
                this.props.record.update({
                    product_id: [result.product_id, result.product_name || ""],
                });
            }
        } else {
            this._openGridConfigurator(false);
        }
    }

    onEditConfiguration() {
        if (this.props.record.data.is_configurable_product) {
            this._openGridConfigurator(true);
        }
    }

    async _openGridConfigurator(edit) {
        const requisitionRecord = this.props.record.model.root;

        await requisitionRecord.update({
            grid_product_tmpl_id: this.props.record.data.product_template_id,
        });

        const updatedLineAttributes = [];
        if (edit) {
            for (const ptnvav of this.props.record.data.product_no_variant_attribute_value_ids.records) {
                updatedLineAttributes.push(ptnvav.resId);
            }
            for (const ptav of this.props.record.data.product_template_attribute_value_ids.records) {
                updatedLineAttributes.push(ptav.resId);
            }
            updatedLineAttributes.sort((a, b) => a - b);
        }

        this._openMatrixConfigurator(
            requisitionRecord.data.grid,
            this.props.record.data.product_template_id[0],
            updatedLineAttributes,
        );

        if (!edit) {
            requisitionRecord.data.line_ids.delete(this.props.record);
        }
    }

    _openMatrixConfigurator(jsonInfo, productTemplateId, editedCellAttributes) {
        const infos = JSON.parse(jsonInfo);
        this.dialog.add(ProductMatrixDialog, {
            header: infos.header,
            rows: infos.matrix,
            editedCellAttributes: editedCellAttributes.toString(),
            product_template_id: productTemplateId,
            record: this.props.record.model.root,
        });
    }
}

PurchaseRequisitionLineProductField.template = "purchase_requisition_product_matrix.PurchaseRequisitionProductField";

export const purchaseRequisitionLineProductField = {
    ...many2OneField,
    component: PurchaseRequisitionLineProductField,
};

registry.category("fields").add("prl_product_many2one", purchaseRequisitionLineProductField);
