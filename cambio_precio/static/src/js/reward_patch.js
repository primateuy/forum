/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { RewardButton } from "@pos_loyalty/app/control_buttons/reward_button/reward_button";

patch(RewardButton.prototype, {
    async _applyReward(reward, coupon_id, potentialQty) {
        // Let standard logic run first
        const result = await super._applyReward(...arguments);

        // Custom behavior example: handle reward types that modify pricelist or fixed price
        if (reward && reward.reward_type === "change_pricelist") {
            const order = this.pos.get_order();
            if (order && reward.pricelist_id) {
                order.set_pricelist(this.pos.pricelists.find(p => p.id === reward.pricelist_id[0]));
            }
        }

        if (reward && reward.reward_type === "fixed_price") {
            const order = this.pos.get_order();
            const line = order?.get_selected_orderline();
            if (line && reward.fixed_price) {
                line.set_unit_price(reward.fixed_price);
            }
        }

        return result;
    },
});