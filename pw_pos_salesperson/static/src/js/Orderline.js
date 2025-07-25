odoo.define('pw_pos_salesperson.Orderline', function (require) {
    'use strict';

    const Orderline = require('point_of_sale.Orderline');
    const Registries = require('point_of_sale.Registries');

    const ResetSalesperson = (Orderline) =>
        class extends Orderline {
            removeUser() {
                this.props.line.remove_sale_person()
            }
            setUser() {
                this.updateSalesperson(this.props.line);
            }
            async updateSalesperson(line) {
                const selectionList = this.env.pos.user.map(user => ({
                    id: user.id,
                    label: user.name,
                    item: user,
                }));

                const { confirmed, payload: selectedUser } = await this.showPopup(
                    'SelectionPopup',
                    {
                        title: this.env._t('Select Salesperson'),
                        list: selectionList,
                    }
                );

                if (!confirmed) return false;

                if (confirmed) {
                    line.set_line_user(selectedUser);
                }
            }
        };

    Registries.Component.extend(Orderline, ResetSalesperson);
    return ResetSalesperson;
});
