/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { Order } from '@point_of_sale/app/store/models';
import { Orderline } from "@point_of_sale/app/store/models";
import { PosStore } from "@point_of_sale/app/store/pos_store";

// Activar para depurar persistencia de puntos de lealtad (consola del navegador).
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

    _getRewardLineValues(args) {
        if (args.reward && args.reward.reward_type === "pricelist_change") {
            return [];
        }
        return super._getRewardLineValues(...arguments);
    },

    /**
     * Incluir coupon_point_changes en el payload.
     * Garantiza que los puntos calculados por Odoo estándar en _updateRewards
     * lleguen siempre al backend aunque otro módulo reemplace export_as_JSON.
     */
    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        if (this.couponPointChanges && Object.keys(this.couponPointChanges).length > 0) {
            json.coupon_point_changes = this.couponPointChanges;
            _log("export_as_JSON: coupon_point_changes incluido en payload", {
                keys: Object.keys(this.couponPointChanges),
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
            line.reward_label = `[Precio Fijo]`;
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

    _updateRewards() {
        if (!this._originalPrices) {
            this._originalPrices = {};
        }
        if (!this._originalPricelistId) {
            this._originalPricelistId = null;
        }

        // PASO 1: Odoo estándar procesa sus recompensas y calcula couponPointChanges.
        // Esto debe ejecutarse SIEMPRE y sin modificaciones previas al estado de la orden.
        let superResult;
        try {
            superResult = super._updateRewards && super._updateRewards(...arguments);
        } catch (error) {
            console.error("Error en super._updateRewards:", error);
            return superResult;
        }

        // PASO 2: Guardar couponPointChanges calculados por Odoo estándar.
        // Nuestra lógica de pricelist/fixed_price puede pisar este valor;
        // lo restauramos al final para que export_as_JSON lo envíe correctamente.
        const savedCouponPointChanges = this.couponPointChanges && Object.keys(this.couponPointChanges).length > 0
            ? JSON.parse(JSON.stringify(this.couponPointChanges))
            : null;
        if (savedCouponPointChanges) {
            _log("_updateRewards: couponPointChanges guardados tras super()", {
                entries: Object.entries(savedCouponPointChanges).map(([k, v]) => ({
                    id: k,
                    points: v.points,
                    program_id: v.program_id,
                })),
            });
        }

        // Verificaciones de seguridad antes de continuar con lógica custom.
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

        // Si no hay recompensas custom, restaurar precios/pricelist y salir.
        if (!this._hasCustomRewards(claimable)) {
            this._restoreOriginalPrices(order);
            this._restoreOriginalPricelist();
            if (savedCouponPointChanges) this.couponPointChanges = savedCouponPointChanges;
            return superResult;
        }

        this._clearRewardLabels();
        const orderlines = order.get_orderlines();

        // ========================================
        // FIXED PRICE
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
        // PRICELIST CHANGE
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
                if (savedCouponPointChanges) this.couponPointChanges = savedCouponPointChanges;
                return superResult;
            }

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
                if (totalPrecio >= rule.minimum_amount && totalCantidad >= rule.minimum_qty) {
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

        // PASO FINAL: Restaurar couponPointChanges para que el backend los reciba
        // intactos, independientemente de los cambios de pricelist que hayamos hecho.
        if (savedCouponPointChanges) {
            this.couponPointChanges = savedCouponPointChanges;
            _log("_updateRewards: couponPointChanges restaurados al final");
        }

        return superResult;
    },

    _restoreOriginalPrices(order) {
        if (!this._originalPrices || Object.keys(this._originalPrices).length === 0) return;
        const orderlines = order ? order.get_orderlines() :
                          (this.pos && this.pos.get_order() ? this.pos.get_order().get_orderlines() : []);
        orderlines.forEach(line => {
            const lineUuid = line.uuid || line.cid;
            const originalData = this._originalPrices[lineUuid];
            if (originalData && originalData.productId === line.product.id) {
                if (line.get_unit_price() !== originalData.price) {
                    line.set_unit_price(originalData.price);
                }
            }
        });
        this._originalPrices = {};
    },

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
    },
});

/**
 * CORRECCIÓN: push_single_order simplificado.
 *
 * Se eliminó la manipulación manual de couponCache. Actualizar couponCache
 * manualmente causaba inconsistencias en el balance de puntos mostrado en el
 * frontend porque:
 * 1. El cache actualizado no coincidía con cómo getLoyaltyPoints() consulta
 *    las tarjetas en memoria, especialmente para tarjetas nuevas.
 * 2. Si el backend aplicaba puntos dobles (bug ya corregido en models.py),
 *    el cache manual multiplicaba el error en la UI.
 *
 * El POS estándar de Odoo refresca automáticamente las tarjetas y puntos al
 * completar la orden (a través del mecanismo de sincronización estándar).
 * Solo garantizamos que coupon_point_changes esté en el payload.
 */
patch(PosStore.prototype, {
    async push_single_order(order) {
        const hasPoints = order.couponPointChanges && Object.keys(order.couponPointChanges).length > 0;
        _log("push_single_order: enviando orden", {
            hasCouponPointChanges: hasPoints,
            keys: hasPoints ? Object.keys(order.couponPointChanges) : [],
        });

        // Wrapper para garantizar coupon_point_changes en el payload incluso si
        // otro módulo sobreescribió export_as_JSON sin llamar a super.
        const originalExport = order.export_as_JSON.bind(order);
        order.export_as_JSON = function () {
            const json = originalExport();
            if (order.couponPointChanges && Object.keys(order.couponPointChanges).length > 0) {
                json.coupon_point_changes = order.couponPointChanges;
                _log("push_single_order: coupon_point_changes inyectado en payload", {
                    keys: Object.keys(json.coupon_point_changes),
                });
            }
            return json;
        };

        try {
            return await super.push_single_order(...arguments);
        } finally {
            // Siempre restaurar export_as_JSON original
            order.export_as_JSON = originalExport;
        }
    },
});
