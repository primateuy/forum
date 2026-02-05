/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { Order } from '@point_of_sale/app/store/models';
import { Orderline } from "@point_of_sale/app/store/models";

function convertPythonDomainToJSON(pythonDomain) {
    if (!pythonDomain || pythonDomain === "[]" || pythonDomain === "") {
        return [];
    }

    let jsonDomain = pythonDomain.replace(/'/g, '"');
    
    jsonDomain = jsonDomain.replace(/\(/g, '[').replace(/\)/g, ']');
    
    jsonDomain = jsonDomain.replace(/\bTrue\b/g, 'true');
    jsonDomain = jsonDomain.replace(/\bFalse\b/g, 'false');
    jsonDomain = jsonDomain.replace(/\bNone\b/g, 'null');
    
    return jsonDomain;
}

function evaluateDomain(domain, record) {
    if (!domain || domain === "[]" || domain === "") {
        return true; 
    }

    let parsedDomain;
    try {
        
        if (typeof domain === 'string') {
            const jsonDomain = convertPythonDomainToJSON(domain);
            parsedDomain = JSON.parse(jsonDomain);
        } else {
            parsedDomain = domain;
        }
    } catch (error) {
        console.error("❌ Error parseando dominio:", domain, error);
        return false;
    }

    if (!Array.isArray(parsedDomain) || parsedDomain.length === 0) {
        return true;
    }

    for (let condition of parsedDomain) {
        if (!Array.isArray(condition)) continue;

        const [field, operator, value] = condition;

        let fieldValue = record[field];
        
        if (Array.isArray(fieldValue) && fieldValue.length >= 1) {
            fieldValue = fieldValue[0]; // Tomar el ID
        }

        // Evaluar según el operador
        switch (operator) {
            case '=':
            case '==':
                if (fieldValue != value) return false;
                break;
            case '!=':
                if (fieldValue == value) return false;
                break;
            case '>':
                if (!(fieldValue > value)) return false;
                break;
            case '>=':
                if (!(fieldValue >= value)) return false;
                break;
            case '<':
                if (!(fieldValue < value)) return false;
                break;
            case '<=':
                if (!(fieldValue <= value)) return false;
                break;
            case 'in':
                if (!Array.isArray(value) || !value.includes(fieldValue)) return false;
                break;
            case 'not in':
                if (Array.isArray(value) && value.includes(fieldValue)) return false;
                break;
            case 'like':
            case 'ilike':
                const fieldStr = String(fieldValue || '').toLowerCase();
                const valueStr = String(value || '').toLowerCase();
                if (!fieldStr.includes(valueStr)) return false;
                break;
            default:
                console.warn(`⚠️ Operador no soportado: ${operator}`);
                return false;
        }
    }

    return true;
}

patch(Orderline.prototype, {
    
    get_full_product_name() {
        const originalName = super.get_full_product_name && super.get_full_product_name.apply(this) || this.product.display_name;
        
        if (this.reward_label && this.reward_type === "fixed_price") {
            return `${originalName} - PRECIO FIJO`;
        }
        
        return originalName;
    },
    
    getDisplayName() {
        return this.get_full_product_name();
    },

    _getBaseProductName() {
        return super.get_full_product_name && super.get_full_product_name.apply(this) || this.product.display_name;
    },

    can_be_merged_with(orderline) {
        const canMerge = super.can_be_merged_with(...arguments);
        
        if (!canMerge) {
            const thisBaseName = this._getBaseProductName();
            const otherBaseName = orderline._getBaseProductName && orderline._getBaseProductName() || 
                                 (orderline.get_full_product_name ? 
                                    orderline.get_full_product_name().replace(/\s*-\s*PRECIO FIJO\s*$/, '') 
                                    : orderline.product.display_name);
            
            if (thisBaseName === otherBaseName) {
                const price = parseFloat(
                    this.pos.utils?.round_di(this.price || 0, this.pos.dp["Product Price"]).toFixed(
                        this.pos.dp["Product Price"]
                    ) || this.price
                );
                const order_line_price = orderline.get_product().get_price(
                    orderline.order.pricelist, 
                    this.get_quantity()
                );
                
                return (
                    !this.skipChange &&
                    orderline.getNote() === this.getNote() &&
                    this.get_product().id === orderline.get_product().id &&
                    this.get_unit() &&
                    this.is_pos_groupable() &&
                    this.get_discount() === 0 &&
                    orderline.get_customer_note() === this.get_customer_note() &&
                    !this.refunded_orderline_id &&
                    !this.isPartOfCombo() &&
                    !orderline.isPartOfCombo()
                );
            }
        }
        
        return canMerge;
    },

    set_quantity(quantity, keep_price) {
        const result = super.set_quantity(...arguments);
        
        if (result && this.order && typeof this.order._updateRewards === 'function') {
            try {
                setTimeout(() => {
                    if (this.order && typeof this.order._updateRewards === 'function') {
                        this.order._updateRewards();
                    }
                }, 0);
            } catch (error) {
                console.error("Error actualizando recompensas en set_quantity:", error);
            }
        }
        
        return result;
    },
});

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

    _productMatchesRuleDomains(product, rulesProductDomains) {
        if (!rulesProductDomains || rulesProductDomains.length === 0) {
            return true; // Sin restricciones de dominio
        }

        return rulesProductDomains.some(ruleDomain => {
            const domain = ruleDomain.product_domain;
            const matches = evaluateDomain(domain, product);
            
            
            
            return matches;
        });
    },

    _updateRewards() {

        if (!this._originalPrices) {
            this._originalPrices = {};
        }
        if (!this._originalPricelistId) {
            this._originalPricelistId = null;
        }
        
        if (!this.pos || !this.pos.get_order) return;
        const order = this.pos.get_order();
        if (!order || !order.get_orderlines) return;
        
        if (!this.pos.rules || !this.pos.pricelists || !this.pos.taxes_by_id) {
            
            return;
        }

        
        super._updateRewards && super._updateRewards(...arguments);
        

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
            return;
        }

        if (!claimable || !Array.isArray(claimable)) return;

        const pricelistReward = claimable.find(
            r => r.reward && r.reward.reward_type === "pricelist_change"
        );

        
        const fixedPriceReward = claimable.find(
            r => r.reward && r.reward.reward_type === "fixed_price"
        );



        if (fixedPriceReward && fixedPriceReward.reward && fixedPriceReward.reward.reward_type === "fixed_price") {
            const reward = fixedPriceReward.reward;
            
            const fixedPrice = reward.fixed_price;
            
            const rulesProductDomains = reward.rules_product_domains || [];
            
            if (fixedPrice !== undefined && fixedPrice !== null && fixedPrice !== false && fixedPrice > 0) {
                
                orderlines.forEach(line => {
                    const productId = line.product.id;
                    const product = line.product;
                    const lineUuid = line.uuid || line.cid;
                    
                    const productMatchesDomain = this._productMatchesRuleDomains(product, rulesProductDomains);
                    
                    
                    if (productMatchesDomain) {
                        if (!this._originalPrices[lineUuid]) {
                            this._originalPrices[lineUuid] = {
                                price: line.get_unit_price(),
                                productId: productId
                            };
                        }
                        
                        if (line.get_unit_price() !== fixedPrice) {
                            line.set_unit_price(fixedPrice);
                        }
                        
                        this._applyRewardLabel(line, reward);
                    } else if (!productMatchesDomain && this._originalPrices[lineUuid]) {
                        const originalData = this._originalPrices[lineUuid];
                        if (originalData && originalData.productId === productId) {
                            line.set_unit_price(originalData.price);
                            delete this._originalPrices[lineUuid];
                        }
                    }
                });
            } else {
                console.warn("⚠️ No se encontró un precio fijo válido en la recompensa");
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

        // ========================================
        // MANEJO DE PRICELIST CHANGE REWARD
        // ========================================
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