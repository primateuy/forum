/** @odoo-module **/


import { Orderline } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";

patch(Orderline.prototype, {
    setup(_defaultObj, options) {
        super.setup(...arguments);
        this.user_id = this.user_id || "";
    },
    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        if (json.user_id) {
            var user = this.get_emp_by_id(json.user_id);
            if (user) {
                this.set_line_emp(user);
            }
        }
    },
    get_emp_by_id (user_id) {
        var self = this;
        var user = null;
        for (var i = 0; i < self.pos.employees.length; i++) {
            if (self.pos.employees[i].id == user_id) {
                user = self.pos.employees[i];
            }
        }
        return user;
    },
    set_line_emp (user) {
        this.user_id = user;
    },
    get_line_emp() {
        return this.user_id;
    },
    remove_sale_person () {
        this.user_id = null;
    },
    get_user_image_url () {
        return (
            (this.user_id &&
                `/web/image?model=res.users&field=image_128&id=${this.user_id.id}&unique=${this.user_id.write_date}`) ||
            ""
        );
        return null;
    },
    getLineUser() {
        if (this.user_id && this.user_id.id !== undefined) {
            return this.user_id;
        }
        return null;
    },
    export_as_JSON() {
        const result = super.export_as_JSON(...arguments);
        if (this.user_id){
            result.user_id = this.user_id.id;
        }
        return result;
    },
});
