/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { Record } from "@web/model/relational_model/record";

patch(FormController.prototype, {
    setup() {
        super.setup();
        this.model.config.mode = "readonly";
    },
    edit(params) {
        var self = this;
        if(this.canEdit && this.model.config.mode === "readonly") {
            this.model.root.config.mode = "edit";
            this.model.load().then(() => {
                self.render(true);
            })
        }
    },
    async saveAndClose() {
        var res = await this.save({ savebtn: true,});
        if (res) { this.model.config.mode = "readonly" }
    },
    async discardAndClose() {
        await this.discard();
        this.model.config.mode = "readonly";
    }
});

patch(Record.prototype, {
    async save(options) {
        var isDirty = await this.isDirty(false);
        if ((!options || !options.savebtn) && isDirty) {
            if (confirm("Would you like to discard the unsaved changes ?") == true) {
                this.model.config.mode = "readonly";
                await this.model.root.discard();
                return super.save(...arguments);
            } else { return false; }
        }
        return super.save(...arguments);
    },
    async isDirty(changeMode = true) {
        var res = await super.isDirty(...arguments);
        if (!res && changeMode) { this.model.config.mode = "readonly"; }
        return res;
    }
})