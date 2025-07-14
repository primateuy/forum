/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { Order } from '@point_of_sale/app/store/models';


// Utilidad local para generar un código aleatorio para reward_identifier_code
function generateRandomRewardCode() {
    return Math.floor(Math.random() * 1e8);
}


patch(Order.prototype, {
   

    _getRewardLineValues(args) {
       
        if (args.reward && args.reward.reward_type === "pricelist_change") {
            let productId = args.reward.discount_line_product_id;
            if (typeof productId === 'object' && productId.id) {
                productId = productId.id;
            }
            const infoProduct = this.pos.db.get_product_by_id(productId);
            if (!infoProduct) {
                const tempProduct = {
                    id: 'pricelist_change_info',
                    display_name: 'Cambio de lista de precios',
                    lst_price: 0,
                    taxes_id: [],
                };
                return [{
                    product: tempProduct,
                    price: 0,
                    quantity: 1,
                    reward_id: args.reward.id,
                    is_reward_line: true,
                    coupon_id: args.coupon_id,
                    points_cost: 0,
                    reward_identifier_code: generateRandomRewardCode(),
                    merge: false,
                }];
            }
            return [{
                product: infoProduct,
                price: 0,
                quantity: 1,
                reward_id: args.reward.id,
                is_reward_line: true,
                coupon_id: args.coupon_id,
                points_cost: 0,
                reward_identifier_code: generateRandomRewardCode(),
                merge: false,
            }];
        }
        return super._getRewardLineValues(...arguments);
    },


    init_from_JSON() {
        super.init_from_JSON(...arguments);
        this._restoringPricelist = false;
    },

    _updateRewardLines() {
        if (this._restoringPricelist) {
            return super._updateRewardLines();
        }

        if (!this.orderlines.length) {
            return super._updateRewardLines();
        }
        
        const rewardLines = this._get_reward_lines();
        if (!rewardLines.length) {
            return super._updateRewardLines();
        }
        
        const pricelistRewardLines = rewardLines.filter(line => {
            if (line.reward_id) {
                const reward = this.pos.reward_by_id[line.reward_id];
                return reward && reward.reward_type === "pricelist_change";
            }
            return false;
        });

        if (pricelistRewardLines.length > 0) {
    
            this._restoringPricelist = true;
            this._restoreDefaultPricelist()
        }

        
        return super._updateRewardLines();
    },

    _restoreDefaultPricelist() {
        const defaultPricelist = this.pos.pricelists.find(p => p.id === 1) || this.pos.pricelists[0];
        
        if (defaultPricelist) {
           
            this.set_pricelist(defaultPricelist);
            if (typeof this._resetTaxesAndPrices === 'function') {
                this._resetTaxesAndPrices();
            }
        } else {
            console.warn("⚠️ No se encontró una lista de precios por defecto");
        }
        
        setTimeout(() => {
            this._restoringPricelist = false;
        }, 100);
    },

    constructor() {
        super.constructor(...arguments);
        this._restoringPricelist = false;
    },
    


    _applyReward(reward, coupon_id, args) {
        
        if (reward.reward_type === "pricelist_change") {
            
            
            if (!this.pos.config.use_pricelist) {
               
                return {
                    error: true,
                    message: "Las listas de precios no están habilitadas en este POS"
                };
            }
            
            
            if (!this.pos.pricelists || this.pos.pricelists.length === 0) {
                
                return {
                    error: true,
                    message: "No hay listas de precios disponibles"
                };
            }

            const pricelistId = reward.discount_max_amount;

            if (!pricelistId || pricelistId <= 0) {
            
            return {
                error: true,
                message: "Lista de precios no configurada en la recompensa"
            };
        }
        
        
        const availablePricelist = this.pos.pricelists.find(p => p.id === pricelistId);
        
        if (!availablePricelist) {
            
            return {
                error: true,
                message: `La lista de precios requerida no está disponible en este POS`
            };
        }
        
        
            
            if(this.pricelist && pricelistId == this.pricelist.id) {
                console.log("⚠️ La lista de precios objetivo es la misma que la actual");
            } else {
const newPricelist = this.pos.pricelists.find(p => p.id === pricelistId);
            if (newPricelist) {
                if (!this.pricelist || this.pricelist.id !== newPricelist.id) {
                    this.set_pricelist(newPricelist);
                    if (typeof this._resetTaxesAndPrices === 'function') {
                        this._resetTaxesAndPrices();
                    }
                    
                } else {
                    console.log("La lista de precios ya está aplicada, no se realiza el cambio.");
                }
            } else {
                console.warn("No se encontró la lista de precios con ID:", pricelistId);
            }
            }
            
            
        }
        // L
        
        return super._applyReward(reward, coupon_id, args);
    },



    
    

});
