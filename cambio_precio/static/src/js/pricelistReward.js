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
        console.error("Error parseando dominio:", domain, error);
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
            fieldValue = fieldValue[0];
        }

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

    // CORRECCIÓN: Se eliminó el patch de set_quantity que disparaba _updateRewards
    // con setTimeout. Esto causaba recálculos asíncronos que interferían con
    // operaciones estándar del POS (borrar líneas, buscar clientes, validar pagos).
    // El _updateRewards() de Odoo ya se dispara automáticamente cuando corresponde
    // a través del mecanismo estándar de recompensas.
});

patch(Order.prototype, {

    _getRewardLineValues(args) {
        if (args.reward && args.reward.reward_type === "pricelist_change") {
            return [];
        }
        return super._getRewardLineValues(...arguments);
    },

    /**
     * No lanzar error cuando la orden se está restaurando desde JSON o cuando se aplica un reward.
     * - Restauración: init_from_JSON crea líneas vía _createLineFromVals → set_quantity.
     * - Aplicar descuento/lealtad: _applyReward crea la línea de descuento y set_quantity llama
     *   assert_editable(); si la orden está finalized por timing/backend, falla "Finalized Order cannot be modified".
     */
    assert_editable() {
        if (this._restoringFromJSON || this._addingRewardLine) {
            return;
        }
        return super.assert_editable(...arguments);
    },

    /**
     * Envuelve la aplicación de recompensas (código de descuento, lealtad) para marcar la orden
     * como "añadiendo línea de reward" y así evitar que assert_editable() lance al crear la línea.
     */
    _applyReward(reward, options) {
        if (typeof super._applyReward !== "function") {
            return;
        }
        this._addingRewardLine = true;
        try {
            return super._applyReward(...arguments);
        } finally {
            this._addingRewardLine = false;
        }
    },

    /**
     * Restaura la orden desde JSON (sesión, servidor, etc.).
     * Marcamos _restoringFromJSON para que assert_editable no lance durante la creación de líneas.
     */
    init_from_JSON(json) {
        this._restoringFromJSON = true;
        try {
            const wasFinalized = json && json.finalized === true;
            if (json) {
                const savedFinalized = json.finalized;
                json.finalized = false;
                super.init_from_JSON(...arguments);
                json.finalized = savedFinalized;
                this.finalized = wasFinalized;
            } else {
                super.init_from_JSON(...arguments);
            }
        } finally {
            this._restoringFromJSON = false;
        }
        this._restoringPricelist = false;
        this._originalPrices = {};
    },

    constructor() {
        super.constructor(...arguments);
        this._restoringPricelist = false;
        this._originalPrices = {};
    },

    // CORRECCIÓN: _clearRewardLabels ahora solo limpia labels de NUESTRAS
    // recompensas custom (fixed_price), no toca las recompensas estándar de Odoo.
    _clearRewardLabels() {
        const orderlines = this.get_orderlines();
        orderlines.forEach(line => {
            if (line.reward_label && line.reward_type === "fixed_price") {
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
            return true;
        }

        return rulesProductDomains.some(ruleDomain => {
            const domain = ruleDomain.product_domain;
            const matches = evaluateDomain(domain, product);
            return matches;
        });
    },

    // CORRECCIÓN: _hasCustomRewards() verifica si hay recompensas custom activas
    // (pricelist_change o fixed_price) entre las reclamables. Si no las hay,
    // _updateRewards() no ejecuta lógica adicional y deja que Odoo estándar 
    // se encargue de todo.
    _hasCustomRewards(claimable) {
        if (!claimable || !Array.isArray(claimable)) return false;
        return claimable.some(r => 
            r.reward && (
                r.reward.reward_type === "pricelist_change" || 
                r.reward.reward_type === "fixed_price"
            )
        );
    },

    _updateRewards() {

        if (!this._originalPrices) {
            this._originalPrices = {};
        }
        if (!this._originalPricelistId) {
            this._originalPricelistId = null;
        }
        
        // CORRECCIÓN CRÍTICA: Primero dejamos que Odoo estándar procese sus
        // recompensas (descuentos, cupones, programas de lealtad, etc.).
        // Esto debe ejecutarse SIEMPRE, sin importar si hay recompensas custom.
        let superResult;
        try {
            superResult = super._updateRewards && super._updateRewards(...arguments);
        } catch (error) {
            console.error("Error en super._updateRewards:", error);
            return superResult;
        }

        // CORRECCIÓN: Verificaciones de seguridad antes de continuar.
        // Si el entorno no está listo, retornamos sin interferir.
        if (!this.pos || !this.pos.get_order) return superResult;
        const order = this.pos.get_order();
        if (!order || !order.get_orderlines) return superResult;
        
        if (!this.pos.rules || !this.pos.pricelists || !this.pos.taxes_by_id) {
            return superResult;
        }

        // CORRECCIÓN: Obtener recompensas reclamables. Si falla (por ejemplo,
        // durante el proceso de pago), retornamos sin interferir.
        let claimable;
        try {
            claimable = this.getClaimableRewards();
        } catch (error) {
            return superResult;
        }

        if (!claimable || !Array.isArray(claimable)) return superResult;

        // CORRECCIÓN CRÍTICA: Si no hay recompensas custom (pricelist_change 
        // o fixed_price), NO ejecutamos ninguna lógica adicional.
        // Esto permite que las promociones estándar de Odoo (descuentos por
        // código, cupones, etc.) funcionen sin interferencia.
        if (!this._hasCustomRewards(claimable)) {
            // Restaurar precios originales si había fixed_price activo antes
            this._restoreOriginalPrices(order);
            // Restaurar pricelist original si había pricelist_change activo antes
            this._restoreOriginalPricelist();
            return superResult;
        }

        // A partir de aquí solo se ejecuta si hay recompensas custom activas.
        this._clearRewardLabels();

        const orderlines = order.get_orderlines();

        // ========================================
        // MANEJO DE FIXED PRICE REWARD
        // ========================================
        const fixedPriceReward = claimable.find(
            r => r.reward && r.reward.reward_type === "fixed_price"
        );

        if (fixedPriceReward && fixedPriceReward.reward) {
            const reward = fixedPriceReward.reward;
            const fixedPrice = reward.fixed_price;
            const rulesProductDomains = reward.rules_product_domains || [];
            
            if (fixedPrice !== undefined && fixedPrice !== null && fixedPrice !== false && fixedPrice > 0) {
                orderlines.forEach(line => {
                    // No tocar líneas de recompensa estándar de Odoo
                    if (line.is_reward_line) return;
                    
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
            }
        } else {
            this._restoreOriginalPrices(order);
        }

        // ========================================
        // MANEJO DE PRICELIST CHANGE REWARD
        // ========================================
        const pricelistReward = claimable.find(
            r => r.reward && r.reward.reward_type === "pricelist_change"
        );

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
                return superResult;
            }

            // Calcular totales solo para las líneas que NO son reward lines
            let totalCantidad = 0;
            let totalBase = 0;
            let totalImpuestos = 0;

            orderlines.forEach(line => {
                if (line.is_reward_line) return;
                
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

            let cumpleAlgunaRegla = false;

            for (const rule of pricelistChangeRules) {
                const cumpleEstaRegla = 
                    totalPrecio >= rule.minimum_amount && 
                    totalCantidad >= rule.minimum_qty;

                if (cumpleEstaRegla) {
                    cumpleAlgunaRegla = true;
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
                this._restoreOriginalPricelist();
            }
        } else {
            this._restoreOriginalPricelist();
        }

        return superResult;
    },

    // CORRECCIÓN: Método extraído para restaurar precios originales.
    // Se llama cuando ya no hay fixed_price reward activo.
    _restoreOriginalPrices(order) {
        if (!this._originalPrices || Object.keys(this._originalPrices).length === 0) return;
        
        const orderlines = order ? order.get_orderlines() : 
                          (this.pos && this.pos.get_order() ? this.pos.get_order().get_orderlines() : []);
        
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
    },

    // CORRECCIÓN: Método extraído para restaurar la pricelist original.
    // Se llama cuando ya no hay pricelist_change reward activo.
    _restoreOriginalPricelist() {
        if (!this._originalPricelistId) return;
        
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
});
