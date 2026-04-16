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
        if (!order || order.finalized) return;
        if (typeof order._applyCustomRewardsOnly === 'function') {
            try {
                order._applyCustomRewardsOnly();
            } catch (e) {
                console.error("[cambio_precio] Error en _applyCustomRewardsOnly (debounced):", e);
            }
        }
    }, delay);
}


const CAMBIO_PRECIO_DEBUG_LOYALTY = false;
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

    set_quantity(quantity, keep_price) {
        const result = super.set_quantity(...arguments);

        // Solo disparar si hay recompensas custom configuradas
        if (this.order && !this.order.finalized) {
            const programs = this.pos?.programs || [];
            const hasCustomPrograms = programs.some(p =>
                p.rewards && p.rewards.some(r =>
                    r.reward_type === 'pricelist_change' ||
                    r.reward_type === 'fixed_price'
                )
            );
            if (hasCustomPrograms) {
                debouncedUpdateRewards(this.order, 150);
            }
        }
        return result;
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


    _applyCustomRewardsOnly() {
        if (!this._originalPrices) this._originalPrices = {};

        if (!this.pos || !this.pos.get_order) return;
        const order = this.pos.get_order();
        if (!order || !order.get_orderlines) return;
        if (!this.pos.rules || !this.pos.pricelists || !this.pos.taxes_by_id) return;

        let claimable;
        try {
            claimable = this.getClaimableRewards();
        } catch (e) {
            return;
        }
        if (!claimable || !Array.isArray(claimable)) return;

        if (!this._hasCustomRewards(claimable)) {
            this._restoreOriginalPrices(order);
            this._restoreOriginalPricelist();
            return;
        }

        const orderlines = order.get_orderlines();

        // --- FIXED PRICE ---
        const fixedPriceRewards = claimable
            .filter(r => r.reward && r.reward.reward_type === "fixed_price")
            .map(r => r.reward);
        if (fixedPriceRewards.length > 0) {
            orderlines.forEach(line => {
                if (line.is_reward_line) return;

                const lineUuid = line.uuid || line.cid;
                const productId = line.product.id;
                const matchingReward = this._getMatchingFixedPriceReward(line, fixedPriceRewards);

                if (matchingReward) {
                    const { reward, fixedPrice } = matchingReward;
                    if (!this._originalPrices[lineUuid]) {
                        this._originalPrices[lineUuid] = { price: line.get_unit_price(), productId };
                    }
                    if (line.get_unit_price() !== fixedPrice) {
                        line.set_unit_price(fixedPrice);
                    }
                    this._applyRewardLabel(line, reward);
                } else if (this._originalPrices[lineUuid]) {
                    const originalData = this._originalPrices[lineUuid];
                    if (originalData && originalData.productId === productId) {
                        if (line.get_unit_price() !== originalData.price) {
                            line.set_unit_price(originalData.price);
                        }
                        delete this._originalPrices[lineUuid];
                    }
                    this._clearRewardLabel(line);
                } else if (line.reward_type === "fixed_price") {
                    this._clearRewardLabel(line);
                }
            });
        } else {
            this._restoreOriginalPrices(order);
            this._clearRewardLabels();
        }

        // --- PRICELIST CHANGE ---
        const pricelistReward = claimable.find(
            r => r.reward && r.reward.reward_type === "pricelist_change"
        );
        if (pricelistReward) {
            if (!this._originalPricelistId) {
                const defaultPricelistId = this.pos?.config?.pricelist_id?.[0];
                this._originalPricelistId = defaultPricelistId || (this.pricelist ? this.pricelist.id : 1);
            }
            const pricelistChangeRules = this.pos.rules.filter(rule => {
                if (!rule.program_id || !rule.program_id.rewards) return false;
                return rule.program_id.rewards.some(r => r.reward_type === 'pricelist_change');
            });
            if (pricelistChangeRules.length === 0) return;

            let totalCantidad = 0, totalBase = 0, totalImpuestos = 0;
            orderlines.forEach(line => {
                if (line.is_reward_line) return;
                const qty = line.get_quantity();
                const unit = line.get_unit_price();
                const base = qty * unit;
                totalBase += base;
                totalCantidad += qty;
                (line.product.taxes_id || []).forEach(taxId => {
                    const tax = this.pos.taxes_by_id[taxId];
                    if (tax) totalImpuestos += base * (tax.amount / 100);
                });
            });
            const totalPrecio = totalBase + totalImpuestos;
            const cumple = pricelistChangeRules.some(
                rule => totalPrecio >= rule.minimum_amount && totalCantidad >= rule.minimum_qty
            );
            if (cumple) {
                const targetPricelistId = pricelistReward.reward.discount_max_amount;
                const targetPricelist = this.pos.pricelists.find(p => p.id === targetPricelistId);
                if (targetPricelist && (!this.pricelist || this.pricelist.id !== targetPricelistId)) {
                    this._restoringPricelist = true;
                    this.set_pricelist(targetPricelist);
                    this._restoringPricelist = false;
                    if (typeof this._resetTaxesAndPrices === 'function') this._resetTaxesAndPrices();
                    this._scheduleCustomRewardsReevaluation();
                }
            } else {
                this._restoreOriginalPricelist();
            }
        } else {
            this._restoreOriginalPricelist();
        }
    },

    deductLoyaltyPoints(reward, coupon) {
        if (reward && (
            reward.reward_type === 'pricelist_change' ||
            reward.reward_type === 'fixed_price'
        )) {
            return [];
        }
        try {
            return super.deductLoyaltyPoints(...arguments);
        } catch (e) {
            console.warn("[cambio_precio] deductLoyaltyPoints error:", e);
        }
    },

    set_pricelist(pricelist) {
        super.set_pricelist(...arguments);
        // Re-evaluar recompensas custom cuando la pricelist cambia desde afuera
        // (p.ej. cambio de cliente). _restoringPricelist impide recursión cuando
        // _applyCustomRewardsOnly o _restoreOriginalPricelist llaman a set_pricelist.
        if (!this._restoringPricelist) {
            debouncedUpdateRewards(this, 150);
        }
    },

    _getRewardLineValues(args) {
        if (args.reward && args.reward.reward_type === "pricelist_change") {
            return [];
        }
        return super._getRewardLineValues(...arguments);
    },

    /**
     * Incluir coupon_point_changes en el payload (igual que el estándar pos_loyalty).
     * Si otro módulo (p. ej. advanced_loyalty_management) no llama a super y construye
     * el JSON desde cero, este patch no se ejecutará al exportar; por eso además
     * inyectamos en push_single_order.
     */
    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        if (this.couponPointChanges && Object.keys(this.couponPointChanges).length > 0) {
            json.coupon_point_changes = this.couponPointChanges;
            _log("export_as_JSON: añadido coupon_point_changes al payload", {
                keys: Object.keys(this.couponPointChanges),
                sample: Object.values(this.couponPointChanges)[0],
            });
        }
        return json;
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

    _scheduleCustomRewardsReevaluation() {
        if (this.finalized) return;
        debouncedUpdateRewards(this, 50);
    },

    _clearRewardLabels() {
        const orderlines = this.get_orderlines();
        orderlines.forEach(line => {
            if (line.reward_label && line.reward_type === "fixed_price") {
                this._clearRewardLabel(line);
            }
        });
    },

    _clearRewardLabel(line) {
        delete line.reward_label;
        delete line.reward_type;
        delete line.reward_badge_color;
        delete line.custom_fixed_price_reward_id;
    },

    _applyRewardLabel(line, reward) {
        if (reward && reward.reward_type === "fixed_price") {
            const label = "Precio Fijo";
            line.reward_label = `[${label}]`;
            line.reward_type = "fixed_price";
            line.reward_badge_color = 'success';
            line.custom_fixed_price_reward_id = reward.id;
        }
    },

    _getFixedPriceForLine(reward, line) {
        if (!reward || !line || !line.product) return null;

        const productId = String(line.product.id);
        const fixedPriceMap = reward.fixed_price_map || {};
        if (Object.prototype.hasOwnProperty.call(fixedPriceMap, productId)) {
            const mappedPrice = Number(fixedPriceMap[productId]);
            return mappedPrice > 0 ? mappedPrice : null;
        }

        const fixedPriceData = reward.fixed_price_data || [];
        const fixedPriceLine = fixedPriceData.find(data => String(data.product_id) === productId);
        if (fixedPriceLine) {
            const dataPrice = Number(fixedPriceLine.fixed_price);
            return dataPrice > 0 ? dataPrice : null;
        }

        const fixedPrice = Number(reward.fixed_price);
        return fixedPrice > 0 ? fixedPrice : null;
    },

    _getMatchingFixedPriceReward(line, fixedPriceRewards) {
        const product = line?.product;
        if (!product) return null;

        for (const reward of fixedPriceRewards) {
            const rulesProductDomains = reward.rules_product_domains || [];
            const productMatchesDomain = this._productMatchesRuleDomains(product, rulesProductDomains);
            const fixedPrice = this._getFixedPriceForLine(reward, line);

            if (productMatchesDomain && fixedPrice !== null) {
                return { reward, fixedPrice };
            }
        }

        return null;
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

    // _updateRewards() {

    //     if (!this._originalPrices) {
    //         this._originalPrices = {};
    //     }
    //     if (!this._originalPricelistId) {
    //         this._originalPricelistId = null;
    //     }

    //     let superResult;
    //     try {
    //         superResult = super._updateRewards && super._updateRewards(...arguments);
    //     } catch (error) {
    //         console.error("Error en super._updateRewards:", error);
    //         return superResult;
    //     }

    //     const savedCouponPointChanges = this.couponPointChanges && Object.keys(this.couponPointChanges).length > 0
    //         ? JSON.parse(JSON.stringify(this.couponPointChanges))
    //         : null;
    //     if (savedCouponPointChanges) {
    //         _log("_updateRewards: puntos guardados tras super", {
    //             numEntries: Object.keys(savedCouponPointChanges).length,
    //             entries: Object.entries(savedCouponPointChanges).map(([k, v]) => ({ id: k, points: v.points, program_id: v.program_id })),
    //         });
    //     }

    //     if (!this.pos || !this.pos.get_order) return superResult;
    //     const order = this.pos.get_order();
    //     if (!order || !order.get_orderlines) return superResult;
    //     if (!this.pos.rules || !this.pos.pricelists || !this.pos.taxes_by_id) return superResult;

    //     let claimable;
    //     try {
    //         claimable = this.getClaimableRewards();
    //     } catch (error) {
    //         if (savedCouponPointChanges) this.couponPointChanges = savedCouponPointChanges;
    //         return superResult;
    //     }
    //     if (!claimable || !Array.isArray(claimable)) return superResult;

    //     if (!this._hasCustomRewards(claimable)) {
    //         this._restoreOriginalPrices(order);
    //         this._restoreOriginalPricelist();
    //         if (savedCouponPointChanges) this.couponPointChanges = savedCouponPointChanges;
    //         return superResult;
    //     }

    //     this._clearRewardLabels();

    //     const orderlines = order.get_orderlines();

    //     const fixedPriceReward = claimable.find(
    //         r => r.reward && r.reward.reward_type === "fixed_price"
    //     );

    //     if (fixedPriceReward && fixedPriceReward.reward) {
    //         const reward = fixedPriceReward.reward;
    //         const fixedPrice = reward.fixed_price;
    //         const rulesProductDomains = reward.rules_product_domains || [];

    //         if (fixedPrice !== undefined && fixedPrice !== null && fixedPrice !== false && fixedPrice > 0) {
    //             orderlines.forEach(line => {
    //                 if (line.is_reward_line) return;

    //                 const productId = line.product.id;
    //                 const product = line.product;
    //                 const lineUuid = line.uuid || line.cid;

    //                 const productMatchesDomain = this._productMatchesRuleDomains(product, rulesProductDomains);

    //                 if (productMatchesDomain) {
    //                     if (!this._originalPrices[lineUuid]) {
    //                         this._originalPrices[lineUuid] = {
    //                             price: line.get_unit_price(),
    //                             productId: productId
    //                         };
    //                     }

    //                     if (line.get_unit_price() !== fixedPrice) {
    //                         line.set_unit_price(fixedPrice);
    //                     }

    //                     this._applyRewardLabel(line, reward);
    //                 } else if (!productMatchesDomain && this._originalPrices[lineUuid]) {
    //                     const originalData = this._originalPrices[lineUuid];
    //                     if (originalData && originalData.productId === productId) {
    //                         line.set_unit_price(originalData.price);
    //                         delete this._originalPrices[lineUuid];
    //                     }
    //                 }
    //             });
    //         }
    //     } else {
    //         this._restoreOriginalPrices(order);
    //     }

    //     const pricelistReward = claimable.find(
    //         r => r.reward && r.reward.reward_type === "pricelist_change"
    //     );

    //     if (pricelistReward) {
    //         if (!this._originalPricelistId) {
    //             const defaultPricelistId = this.pos?.config?.pricelist_id?.[0];
    //             this._originalPricelistId = defaultPricelistId || (this.pricelist ? this.pricelist.id : 1);
    //         }

    //         const pricelistChangeRules = this.pos.rules.filter(rule => {
    //             if (!rule.program_id || !rule.program_id.rewards) return false;
    //             return rule.program_id.rewards.some(
    //                 reward => reward.reward_type === 'pricelist_change'
    //             );
    //         });

    //         if (pricelistChangeRules.length === 0) {
    //             if (savedCouponPointChanges) this.couponPointChanges = savedCouponPointChanges;
    //             return superResult;
    //         }

    //         let totalCantidad = 0;
    //         let totalBase = 0;
    //         let totalImpuestos = 0;

    //         orderlines.forEach(line => {
    //             if (line.is_reward_line) return;

    //             const quantity = line.get_quantity();
    //             const unitPrice = line.get_unit_price();
    //             const baseLine = quantity * unitPrice;

    //             totalBase += baseLine;
    //             totalCantidad += quantity;

    //             const productTaxes = line.product.taxes_id || [];
    //             productTaxes.forEach(taxId => {
    //                 const tax = this.pos.taxes_by_id[taxId];
    //                 if (tax) {
    //                     totalImpuestos += baseLine * (tax.amount / 100);
    //                 }
    //             });
    //         });

    //         const totalPrecio = totalBase + totalImpuestos;

    //         let cumpleAlgunaRegla = false;

    //         for (const rule of pricelistChangeRules) {
    //             const cumpleEstaRegla =
    //                 totalPrecio >= rule.minimum_amount &&
    //                 totalCantidad >= rule.minimum_qty;

    //             if (cumpleEstaRegla) {
    //                 cumpleAlgunaRegla = true;
    //                 break;
    //             }
    //         }

    //         if (cumpleAlgunaRegla) {
    //             const targetPricelistId = pricelistReward.reward.discount_max_amount;
    //             const targetPricelist = this.pos.pricelists.find(p => p.id === targetPricelistId);

    //             if (targetPricelist && (!this.pricelist || this.pricelist.id !== targetPricelistId)) {
    //                 this.set_pricelist(targetPricelist);

    //                 if (typeof this._resetTaxesAndPrices === 'function') {
    //                     this._resetTaxesAndPrices();
    //                 }
    //             }
    //         } else {
    //             this._restoreOriginalPricelist();
    //         }
    //     } else {
    //         this._restoreOriginalPricelist();
    //     }

    //     // Restaurar puntos de lealtad para que no se pierdan (p. ej. al cambiar pricelist).
    //     if (savedCouponPointChanges) {
    //         this.couponPointChanges = savedCouponPointChanges;
    //         _log("_updateRewards: puntos restaurados al final");
    //     }

    //     return superResult;
    // },

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
            this._restoringPricelist = true;
            this.set_pricelist(original);
            this._restoringPricelist = false;

            if (typeof this._resetTaxesAndPrices === 'function') {
                this._resetTaxesAndPrices();
            }
            this._scheduleCustomRewardsReevaluation();
        }

        this._originalPricelistId = null;
    }
});

/**
 * Asegura que el payload enviado al backend incluya coupon_point_changes.
 * Otros módulos (p. ej. advanced_loyalty_management) pueden reemplazar
 * Order.export_as_JSON sin llamar a super, por lo que el payload puede
 * no incluir los puntos. Aquí envolvemos la orden antes de enviarla para
 * que cualquier llamada a export_as_JSON devuelva también coupon_point_changes.
 */
patch(PosStore.prototype, {
    async push_single_order(order) {
        const hasPoints = order.couponPointChanges && Object.keys(order.couponPointChanges).length > 0;
        _log("push_single_order: llamada", {
            hasCouponPointChanges: hasPoints,
            keys: hasPoints ? Object.keys(order.couponPointChanges) : [],
        });

        const originalExport = order.export_as_JSON.bind(order);
        order.export_as_JSON = function () {
            const json = originalExport();
            if (order.couponPointChanges && Object.keys(order.couponPointChanges).length > 0) {
                json.coupon_point_changes = order.couponPointChanges;
                _log("push_single_order (wrapper export_as_JSON): inyectado coupon_point_changes", {
                    keys: Object.keys(json.coupon_point_changes),
                    hasInPayload: "coupon_point_changes" in json,
                });
            } else {
                _log("push_single_order (wrapper export_as_JSON): orden sin couponPointChanges, no se inyecta");
            }
            return json;
        };
        try {
            const result = await super.push_single_order(...arguments);
            // Actualizar couponCache en el POS para que el "Points Balance" muestre el saldo
            // ya persistido en backend; si no, la siguiente pantalla sigue mostrando el saldo viejo.
            if (result && hasPoints && order.couponPointChanges) {
                if (!this.couponCache) this.couponCache = {};
                const cache = { ...this.couponCache };
                for (const [couponIdStr, change] of Object.entries(order.couponPointChanges)) {
                    const points = change && typeof change.points === 'number' ? change.points : 0;
                    if (points === 0) continue;
                    const couponId = isNaN(Number(couponIdStr)) ? couponIdStr : Number(couponIdStr);
                    const prev = cache[couponId];
                    const currentBalance = (prev && typeof prev.balance === 'number') ? prev.balance : 0;
                    cache[couponId] = { ...(prev || {}), id: couponId, balance: currentBalance + points };
                }
                this.couponCache = cache;
                _log("push_single_order: actualizado couponCache tras éxito", {
                    keys: Object.keys(order.couponPointChanges),
                });
            }
            return result;
        } finally {
            order.export_as_JSON = originalExport;
        }
    },
});
