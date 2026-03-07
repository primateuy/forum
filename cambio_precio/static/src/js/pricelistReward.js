/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { Order } from '@point_of_sale/app/store/models';
import { Orderline } from "@point_of_sale/app/store/models";
import { PosStore } from "@point_of_sale/app/store/pos_store";


let _updateRewardsDebounceTimer = null;

function debouncedUpdateRewards(order, delay = 150) {
    if (_updateRewardsDebounceTimer) {
        clearTimeout(_updateRewardsDebounceTimer);
    }
    _updateRewardsDebounceTimer = setTimeout(() => {
        _updateRewardsDebounceTimer = null;
        if (order && typeof order._updateRewards === 'function') {
            if (order.finalized) {
                return;
            }
            try {
                order._updateRewards();
            } catch (e) {
                console.error("[cambio_precio] Error en _updateRewards (debounced):", e);
            }
        }
    }, delay);
}

const CAMBIO_PRECIO_DEBUG_LOYALTY = true;
function _log(msg, data) {
    if (CAMBIO_PRECIO_DEBUG_LOYALTY && typeof console !== "undefined" && console.log) {
        if (data !== undefined) console.log("[cambio_precio]", msg, data);
        else console.log("[cambio_precio]", msg);
    }
}

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

    set_unit_price(price) {
        return super.set_unit_price(...arguments);
    },

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

    set_quantity(quantity, keep_price) {
        const result = super.set_quantity(...arguments);
        if (this.order) {
            debouncedUpdateRewards(this.order, 150);
        }
        return result;
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
});

patch(Order.prototype, {

    finalize() {
        if (_updateRewardsDebounceTimer) {
            clearTimeout(_updateRewardsDebounceTimer);
            _updateRewardsDebounceTimer = null;
        }
        return super.finalize(...arguments);
    },

    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        if (this.couponPointChanges && Object.keys(this.couponPointChanges).length > 0) {
            json.coupon_point_changes = this.couponPointChanges;
        }
        return json;
    },

    init_from_JSON() {
        super.init_from_JSON(...arguments);
        this._restoringPricelist = false;
        this._originalPrices = {};
        this._basePrices = {}; // Precios base sin ningún descuento (usados para calcular umbral de pricelist)
    },

    constructor() {
        super.constructor(...arguments);
        this._restoringPricelist = false;
        this._originalPrices = {};
        this._basePrices = {};
    },

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
            return evaluateDomain(domain, product);
        });
    },

    _hasCustomRewards(claimable) {
        if (!claimable || !Array.isArray(claimable)) return false;
        return claimable.some(r =>
            r.reward && (
                r.reward.reward_type === "pricelist_change" ||
                r.reward.reward_type === "fixed_price"
            )
        );
    },

    /**
     * CORRECCIÓN LOOP INFINITO: Calcula el total de la orden usando SOLO las
     * líneas de producto base, excluyendo reward lines (descuentos de cupones,
     * etc.). Usa los precios base guardados al inicio de _updateRewards,
     * que son intactos y no dependen de ningún descuento aplicado.
     * De esta forma el umbral de activación de la pricelist es ESTABLE y no oscila.
     */
    _calcularTotalesParaPricelist(orderlines) {
        let totalCantidad = 0;
        let totalBase = 0;
        let totalImpuestos = 0;

        orderlines.forEach(line => {
            // Excluir reward lines (descuentos, puntos, etc.)
            if (line.is_reward_line) return;

            const quantity = line.get_quantity();
            const lineUuid = line.uuid || line.cid;
            
            // CRÍTICO: usar SIEMPRE _basePrices que se guarda al inicio
            // sin ninguna modificación. Esto garantiza que el umbral nunca oscila.
            const basePrice = this._basePrices && this._basePrices[lineUuid];
            const unitPrice = basePrice !== undefined ? basePrice : line.get_unit_price();

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

        return { totalCantidad, totalBase, totalPrecio: totalBase + totalImpuestos };
    },

    _updateRewards() {
        if (this.finalized) return;

        // Guard principal: evita re-entrada directa
        if (this._isUpdatingRewards) return;
        this._isUpdatingRewards = true;

        try {
            if (!this._originalPrices) this._originalPrices = {};
            if (!this._basePrices) this._basePrices = {};
            if (!this._originalPricelistId) this._originalPricelistId = null;

            // CRÍTICO: Guardar precios base del estado ACTUAL (sin ninguna modificación aún).
            // Estos precios se usan para calcular el umbral de pricelist y nunca cambian,
            // lo que evita la oscilación entre aplicar/remover la pricelist.
            const currentOrder = this.pos && this.pos.get_order();
            if (currentOrder && currentOrder.get_orderlines) {
                const currentLines = currentOrder.get_orderlines();
                currentLines.forEach(line => {
                    if (line.is_reward_line) return;
                    const lineUuid = line.uuid || line.cid;
                    // Si ya existe, no sobrescribir (mantener el precio más puro)
                    if (!this._basePrices[lineUuid]) {
                        this._basePrices[lineUuid] = line.get_unit_price();
                        
                    }
                });
            }

            let superResult;
            try {
                superResult = super._updateRewards && super._updateRewards(...arguments);
            } catch (error) {
                console.error("Error en super._updateRewards:", error);
                return superResult;
            }

            const savedCouponPointChanges = this.couponPointChanges && Object.keys(this.couponPointChanges).length > 0
                ? JSON.parse(JSON.stringify(this.couponPointChanges))
                : null;
            
            if (!this.pos || !this.pos.get_order) return superResult;
            const order = this.pos.get_order();
            if (!order || !order.get_orderlines) return superResult;
            if (!this.pos.rules || !this.pos.pricelists || !this.pos.taxes_by_id) return superResult;

            let claimable;
            try {
                claimable = this.getClaimableRewards();
            } catch (error) {
                if (savedCouponPointChanges) this.couponPointChanges = savedCouponPointChanges;
                return superResult;
            }

            

            if (!claimable || !Array.isArray(claimable)) return superResult;

            if (!this._hasCustomRewards(claimable)) {
                this._restoreOriginalPrices(order);
                this._restoreOriginalPricelist();
                if (savedCouponPointChanges) this.couponPointChanges = savedCouponPointChanges;
                return superResult;
            }

            this._clearRewardLabels();

            const orderlines = order.get_orderlines();

            // ========================================
            // MANEJO DE FIXED PRICE REWARD
            // ========================================
            const fixedPriceReward = claimable.find(r => r.reward && r.reward.reward_type === "fixed_price");

            if (fixedPriceReward && fixedPriceReward.reward) {
                const reward = fixedPriceReward.reward;
                const fixedPrice = reward.fixed_price;
                const rulesProductDomains = reward.rules_product_domains || [];

                if (fixedPrice !== undefined && fixedPrice !== null && fixedPrice !== false && fixedPrice > 0) {
                    orderlines.forEach(line => {
                        if (line.is_reward_line) return;

                        const productId = line.product.id;
                        const product = line.product;
                        const lineUuid = line.uuid || line.cid;
                        const productMatchesDomain = this._productMatchesRuleDomains(product, rulesProductDomains);

                        if (productMatchesDomain) {
                            if (!this._originalPrices[lineUuid]) {
                                this._originalPrices[lineUuid] = {
                                    price: line.get_unit_price(),
                                    productId,
                                };
                            }
                            if (line.get_unit_price() !== fixedPrice) {
                                line._settingFixedPrice = true;
                                try {
                                    line.set_unit_price(fixedPrice);
                                } finally {
                                    line._settingFixedPrice = false;
                                }
                            }
                            this._applyRewardLabel(line, reward);
                        } else if (this._originalPrices[lineUuid]) {
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
            const pricelistReward = claimable.find(r => r.reward && r.reward.reward_type === "pricelist_change");

            if (pricelistReward) {
                if (!this._originalPricelistId) {
                    this._originalPricelistId = this.pricelist ? this.pricelist.id : 1;
                }

                const pricelistChangeRules = this.pos.rules.filter(rule => {
                    if (!rule.program_id || !rule.program_id.rewards) return false;
                    return rule.program_id.rewards.some(r => r.reward_type === 'pricelist_change');
                });

                if (pricelistChangeRules.length === 0) {
                    if (savedCouponPointChanges) this.couponPointChanges = savedCouponPointChanges;
                    return superResult;
                }

                // CORRECCIÓN: usamos _calcularTotalesParaPricelist que excluye
                // reward lines y usa _basePrices (precios sin modificación alguna),
                // evitando completamente la oscilación del umbral.
                const { totalCantidad, totalPrecio } = this._calcularTotalesParaPricelist(orderlines);

                

                let cumpleAlgunaRegla = false;
                for (const rule of pricelistChangeRules) {
                    if (totalPrecio >= rule.minimum_amount && totalCantidad >= rule.minimum_qty) {
                        cumpleAlgunaRegla = true;
                        break;
                    }
                }

                if (cumpleAlgunaRegla) {
                    const targetPricelistId = pricelistReward.reward.discount_max_amount;
                    const targetPricelist = this.pos.pricelists.find(p => p.id === targetPricelistId);

                    if (targetPricelist && (!this.pricelist || this.pricelist.id !== targetPricelistId)) {
                        // CORRECCIÓN: bloqueamos _updateRewards durante set_pricelist
                        // para que el cambio de pricelist no dispare un nuevo ciclo.
                        this._isUpdatingRewards = true;
                        try {
                            this.set_pricelist(targetPricelist);
                            if (typeof this._resetTaxesAndPrices === 'function') {
                                this._resetTaxesAndPrices();
                            }
                        } finally {
                            // Se restaura en el bloque finally externo al salir de _updateRewards
                        }
                    }
                } else {
                    this._restoreOriginalPricelist();
                }
            } else {
                this._restoreOriginalPricelist();
            }

            if (savedCouponPointChanges) {
                this.couponPointChanges = savedCouponPointChanges;
            }

            return superResult;
        } finally {
            this._isUpdatingRewards = false;
        }
    },

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
                    line._settingFixedPrice = true;
                    try {
                        line.set_unit_price(originalData.price);
                    } finally {
                        line._settingFixedPrice = false;

                        delete line.reward_label;
                        delete line.reward_type;
                        delete line.reward_badge_color;
                    }
                }
            }
        });

        this._originalPrices = {};
    },

    _restoreOriginalPricelist() {
        if (!this._originalPricelistId) return;

        const original = this.pos.pricelists.find(p => p.id === this._originalPricelistId);

        if (original && this.pricelist?.id !== original.id) {
            // CORRECCIÓN: bloqueamos re-entrada también al restaurar pricelist
            this._isUpdatingRewards = true;
            try {
                this.set_pricelist(original);
                if (typeof this._resetTaxesAndPrices === 'function') {
                    this._resetTaxesAndPrices();
                }
            } finally {
                this._isUpdatingRewards = false;
            }
        }

        this._originalPricelistId = null;
        // Limpiar precios base cuando se restaura la pricelist original,
        // para que la próxima vez que se aplique, vuelva a guardarse correctamente
        this._basePrices = {};
    },
});

patch(PosStore.prototype, {
    async push_single_order(order) {
        const hasPoints = order.couponPointChanges && Object.keys(order.couponPointChanges).length > 0;
        

        const couponPointChangesSnapshot = hasPoints
            ? JSON.parse(JSON.stringify(order.couponPointChanges))
            : null;

        const originalExport = order.export_as_JSON.bind(order);
        order.export_as_JSON = function () {
            const json = originalExport();
            if (couponPointChangesSnapshot) {
                json.coupon_point_changes = couponPointChangesSnapshot;
               
            }
            return json;
        };

        try {
            const result = await super.push_single_order(...arguments);

            if (result && hasPoints && couponPointChangesSnapshot) {
                try {
                    const partnerId = order.get_client && order.get_client()
                        ? order.get_client().id
                        : null;

                    if (partnerId && typeof this._refreshLoyaltyCoupons === 'function') {
                        await this._refreshLoyaltyCoupons(partnerId);
                        
                    } else if (typeof this.fetchLoyaltyCard === 'function') {
                        for (const couponIdStr of Object.keys(couponPointChangesSnapshot)) {
                            const couponId = Number(couponIdStr);
                            if (!isNaN(couponId) && couponId > 0) {
                                try {
                                    await this.fetchLoyaltyCard(couponId);
                                } catch (e) {
                                    _log("push_single_order: error recargando cupón individual", { couponId, e });
                                }
                            }
                        }
                    } else {
                        // Fallback: invalidar cache para que la próxima consulta
                        // traiga datos frescos del backend
                        if (this.couponCache) {
                            for (const couponIdStr of Object.keys(couponPointChangesSnapshot)) {
                                const couponId = isNaN(Number(couponIdStr)) ? couponIdStr : Number(couponIdStr);
                                delete this.couponCache[couponId];
                            }
                        }
                    }
                } catch (refreshErr) {
                    console.warn("[cambio_precio] push_single_order: error al recargar cupones", refreshErr);
                }
            }

            return result;
        } finally {
            order.export_as_JSON = originalExport;
        }
    },
});