/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { Order } from '@point_of_sale/app/store/models';
import { Orderline } from "@point_of_sale/app/store/models";

// Patch para Orderline para mostrar el nombre con etiqueta
patch(Orderline.prototype, {
    
    get_full_product_name() {
        const originalName = super.get_full_product_name && super.get_full_product_name.apply(this) || this.product.display_name;
        
        // Si tiene etiqueta de recompensa Y el tipo es "fixed_price", agregarla al nombre
        if (this.reward_label && this.reward_type === "fixed_price") {
            return `${originalName} - PRECIO FIJO`;
        }
        
        return originalName;
    },
    
    // Método adicional para obtener el nombre con etiqueta
    getDisplayName() {
        return this.get_full_product_name();
    }
});

// Patch para Order - manejo de recompensas
patch(Order.prototype, {

    _getRewardLineValues(args) {
        if (args.reward && args.reward.reward_type === "pricelist_change") {
            return [];
        }
        return super._getRewardLineValues(...arguments);
    },

    init_from_JSON() {
        super.init_from_JSON(...arguments);
        this._restoringPricelist = false;
        this._originalPrices = {};
    },

    constructor() {
        super.constructor(...arguments);
        this._restoringPricelist = false;
        this._originalPrices = {};
    },

    // Método para limpiar etiquetas de recompensa
    _clearRewardLabels() {
        const orderlines = this.get_orderlines();
        orderlines.forEach(line => {
            if (line.reward_label) {
                delete line.reward_label;
                delete line.reward_type;
                delete line.reward_badge_color;
            }
        });
    },

    _applyRewardLabel(line, reward) {
        if (reward && reward.reward_type === "fixed_price") {
            const label = "Precio Fijo";
            line.reward_label = `[${label}]`;
            line.reward_type = "fixed_price";  
            line.reward_badge_color = 'success';
        }
    },

    _updateRewards() {
        super._updateRewards && super._updateRewards(...arguments);
        
        const order = this.pos.get_order();
        if (!order) return;

        if (!this._originalPrices) {
            this._originalPrices = {};
        }
        if (!this._originalPricelistId) {
            this._originalPricelistId = null;
        }

        this._clearRewardLabels();

        const orderlines = order.get_orderlines();
        let totalCantidad = 0;
        let totalBase = 0;
        let totalImpuestos = 0;

        orderlines.forEach(line => {
            const quantity = line.get_quantity();
            const unitPrice = line.get_unit_price();
            const baseLine = quantity * unitPrice;

            totalBase += baseLine;
            totalCantidad += quantity;

            const productTaxes = line.product.taxes_id || [];
            productTaxes.forEach(taxId => {
                const tax = this.pos.taxes_by_id[taxId];
                if (tax) {
                    totalImpuestos += baseLine * (tax.amount / 100);
                }
            });
        });

        const totalPrecio = totalBase + totalImpuestos;

        let claimable;
        try {
            claimable = this.getClaimableRewards();
        } catch (error) {
            console.error("❌ Error obteniendo recompensas:", error);
            return;
        }

        if (!claimable || !Array.isArray(claimable)) return;

        const pricelistReward = claimable.find(
            r => r.reward && r.reward.reward_type === "pricelist_change"
        );
        
        const fixedPriceReward = claimable.find(
            r => r.reward && r.reward.reward_type === "fixed_price"
        );

        // ========================================
        // MANEJO DE FIXED PRICE REWARD
        // ========================================
        if (fixedPriceReward && fixedPriceReward.reward && fixedPriceReward.reward.reward_type === "fixed_price") {
            const reward = fixedPriceReward.reward;
            let priceMap = reward.fixed_price_map;
            
            // Si fixed_price_map no está, intentar con fixed_price_data
            if (!priceMap && reward.fixed_price_data) {
                const dataArray = reward.fixed_price_data;
                if (Array.isArray(dataArray)) {
                    priceMap = {};
                    dataArray.forEach(item => {
                        priceMap[item.product_id] = item.fixed_price;
                    });
                }
            }
            
            if (priceMap && Object.keys(priceMap).length > 0) {
                
                orderlines.forEach(line => {
                    const productId = line.product.id;
                    const fixedPrice = priceMap[productId];
                    const lineUuid = line.uuid || line.cid;
                    
                    if (fixedPrice !== undefined) {
                        if (!this._originalPrices[lineUuid]) {
                            this._originalPrices[lineUuid] = {
                                price: line.get_unit_price(),
                                productId: productId
                            };
                            
                        }
                        
                        // Aplicar precio fijo solo si es diferente
                        if (line.get_unit_price() !== fixedPrice) {
                            line.set_unit_price(fixedPrice);
                        }
                        
                        // Aplicar etiqueta SOLO AQUÍ para FIXED PRICE
                        this._applyRewardLabel(line, reward);
                    }
                });
            } 
        } else {
            if (Object.keys(this._originalPrices).length > 0) { 
                
                orderlines.forEach(line => {
                    const lineUuid = line.uuid || line.cid;
                    const originalData = this._originalPrices[lineUuid];
                    
                    if (originalData && originalData.productId === line.product.id) {
                        const currentPrice = line.get_unit_price();
                        
                        if (currentPrice !== originalData.price) {
                            line.set_unit_price(originalData.price);
                        }
                    }
                });
                
                this._originalPrices = {};
            }
        }

       
        if (pricelistReward) {
            if (!this._originalPricelistId) {
                this._originalPricelistId = this.pricelist ? this.pricelist.id : 1;
            }

            const pricelistChangeRules = this.pos.rules.filter(rule => {
                if (!rule.program_id || !rule.program_id.rewards) return false;
                
                return rule.program_id.rewards.some(
                    reward => reward.reward_type === 'pricelist_change'
                );
            });

            if (pricelistChangeRules.length === 0) {
                console.warn("⚠️ No hay reglas de pricelist_change");
                return;
            }

            let cumpleAlgunaRegla = false;
            let reglaCumplida = null;

            for (const rule of pricelistChangeRules) {
                const cumpleEstaRegla = 
                    totalPrecio >= rule.minimum_amount && 
                    totalCantidad >= rule.minimum_qty;

                if (cumpleEstaRegla) {
                    cumpleAlgunaRegla = true;
                    reglaCumplida = rule;
                    break;
                }
            }

            if (cumpleAlgunaRegla) {
                const targetPricelistId = pricelistReward.reward.discount_max_amount;
                const targetPricelist = this.pos.pricelists.find(p => p.id === targetPricelistId);
                
                if (targetPricelist && (!this.pricelist || this.pricelist.id !== targetPricelistId)) {
                    this.set_pricelist(targetPricelist);
                    
                    if (typeof this._resetTaxesAndPrices === 'function') {
                        this._resetTaxesAndPrices();
                    }
                }
            } else {
                // Restaurar lista original
                if (this._originalPricelistId) {
                    const original = this.pos.pricelists.find(
                        p => p.id === this._originalPricelistId
                    );
                    
                    if (original && this.pricelist?.id !== original.id) {
                        this.set_pricelist(original);
                        
                        if (typeof this._resetTaxesAndPrices === 'function') {
                            this._resetTaxesAndPrices();
                        }
                    }
                }
            }
        } else {
            // No hay recompensa de pricelist activa - restaurar
            if (this._originalPricelistId) {
                const original = this.pos.pricelists.find(
                    p => p.id === this._originalPricelistId
                );
                
                if (original && this.pricelist?.id !== original.id) {
                    this.set_pricelist(original);
                    
                    if (typeof this._resetTaxesAndPrices === 'function') {
                        this._resetTaxesAndPrices();
                    }
                }
                
                this._originalPricelistId = null;
            }
        }
    }
});