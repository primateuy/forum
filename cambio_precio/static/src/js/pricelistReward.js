/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { Order } from '@point_of_sale/app/store/models';
import { Orderline } from "@point_of_sale/app/store/models";
import { PosStore } from "@point_of_sale/app/store/pos_store";

const CAMBIO_PRECIO_DEBUG_LOYALTY = true;
function _log(msg, data) {
    if (CAMBIO_PRECIO_DEBUG_LOYALTY && typeof console !== "undefined" && console.log) {
        if (data !== undefined) console.log("[cambio_precio]", msg, data);
        else console.log("[cambio_precio]", msg);
    }
}

function convertPythonDomainToJSON(pythonDomain) {
    if (!pythonDomain || pythonDomain === "[]" || pythonDomain === "") return [];
    let jsonDomain = pythonDomain.replace(/'/g, '"');
    jsonDomain = jsonDomain.replace(/\(/g, '[').replace(/\)/g, ']');
    jsonDomain = jsonDomain.replace(/\bTrue\b/g, 'true');
    jsonDomain = jsonDomain.replace(/\bFalse\b/g, 'false');
    jsonDomain = jsonDomain.replace(/\bNone\b/g, 'null');
    return jsonDomain;
}

function evaluateDomain(domain, record) {
    if (!domain || domain === "[]" || domain === "") return true;
    let parsedDomain;
    try {
        parsedDomain = typeof domain === 'string' ? JSON.parse(convertPythonDomainToJSON(domain)) : domain;
    } catch (error) {
        console.error("Error parseando dominio:", domain, error);
        return false;
    }
    if (!Array.isArray(parsedDomain) || parsedDomain.length === 0) return true;
    for (let condition of parsedDomain) {
        if (!Array.isArray(condition)) continue;
        const [field, operator, value] = condition;
        let fieldValue = record[field];
        if (Array.isArray(fieldValue) && fieldValue.length >= 1) fieldValue = fieldValue[0];
        switch (operator) {
            case '=': case '==': if (fieldValue != value) return false; break;
            case '!=': if (fieldValue == value) return false; break;
            case '>': if (!(fieldValue > value)) return false; break;
            case '>=': if (!(fieldValue >= value)) return false; break;
            case '<': if (!(fieldValue < value)) return false; break;
            case '<=': if (!(fieldValue <= value)) return false; break;
            case 'in': if (!Array.isArray(value) || !value.includes(fieldValue)) return false; break;
            case 'not in': if (Array.isArray(value) && value.includes(fieldValue)) return false; break;
            case 'like': case 'ilike':
                if (!String(fieldValue || '').toLowerCase().includes(String(value || '').toLowerCase())) return false;
                break;
            default: return false;
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

    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        if (this.couponPointChanges && Object.keys(this.couponPointChanges).length > 0) {
            json.coupon_point_changes = this.couponPointChanges;
            _log("export_as_JSON: coupon_point_changes incluido", { keys: Object.keys(this.couponPointChanges) });
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
        this.get_orderlines().forEach(line => {
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
        if (!rulesProductDomains || rulesProductDomains.length === 0) return true;
        return rulesProductDomains.some(ruleDomain => evaluateDomain(ruleDomain.product_domain, product));
    },

    _hasCustomRewards(claimable) {
        if (!claimable || !Array.isArray(claimable)) return false;
        return claimable.some(r =>
            r.reward && (r.reward.reward_type === "pricelist_change" || r.reward.reward_type === "fixed_price")
        );
    },

    _updateRewards() {
        if (!this._originalPrices) this._originalPrices = {};
        if (!this._originalPricelistId) this._originalPricelistId = null;

        let superResult;
        try {
            superResult = super._updateRewards && super._updateRewards(...arguments);
        } catch (error) {
            console.error("Error en super._updateRewards:", error);
            return superResult;
        }

        // Guardar couponPointChanges calculados por Odoo estándar ANTES de nuestra
        // lógica custom. set_pricelist() los borra; los restauramos al final para
        // que _postPushOrderResolve los reciba correctos y llame a confirm_coupon_programs.
        const savedCouponPointChanges = this.couponPointChanges && Object.keys(this.couponPointChanges).length > 0
            ? JSON.parse(JSON.stringify(this.couponPointChanges))
            : null;

        if (savedCouponPointChanges) {
            _log("_updateRewards: couponPointChanges guardados", {
                entries: Object.entries(savedCouponPointChanges).map(([k, v]) => ({ id: k, points: v.points })),
            });
        }

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

        // ========== FIXED PRICE ==========
        const fixedPriceReward = claimable.find(r => r.reward && r.reward.reward_type === "fixed_price");
        if (fixedPriceReward && fixedPriceReward.reward) {
            const reward = fixedPriceReward.reward;
            const fixedPrice = reward.fixed_price;
            const rulesProductDomains = reward.rules_product_domains || [];
            if (fixedPrice !== undefined && fixedPrice !== null && fixedPrice !== false && fixedPrice > 0) {
                orderlines.forEach(line => {
                    if (line.is_reward_line) return;
                    const productId = line.product.id;
                    const lineUuid = line.uuid || line.cid;
                    const productMatchesDomain = this._productMatchesRuleDomains(line.product, rulesProductDomains);
                    if (productMatchesDomain) {
                        if (!this._originalPrices[lineUuid]) {
                            this._originalPrices[lineUuid] = { price: line.get_unit_price(), productId };
                        }
                        if (line.get_unit_price() !== fixedPrice) line.set_unit_price(fixedPrice);
                        this._applyRewardLabel(line, reward);
                    } else if (this._originalPrices[lineUuid]) {
                        const orig = this._originalPrices[lineUuid];
                        if (orig.productId === productId) {
                            line.set_unit_price(orig.price);
                            delete this._originalPrices[lineUuid];
                        }
                    }
                });
            }
        } else {
            this._restoreOriginalPrices(order);
        }

        // ========== PRICELIST CHANGE ==========
        const pricelistReward = claimable.find(r => r.reward && r.reward.reward_type === "pricelist_change");
        if (pricelistReward) {
            if (!this._originalPricelistId) {
                this._originalPricelistId = this.pricelist ? this.pricelist.id : 1;
            }
            const pricelistChangeRules = this.pos.rules.filter(rule => {
                if (!rule.program_id || !rule.program_id.rewards) return false;
                return rule.program_id.rewards.some(r => r.reward_type === 'pricelist_change');
            });
            if (!pricelistChangeRules.length) {
                if (savedCouponPointChanges) this.couponPointChanges = savedCouponPointChanges;
                return superResult;
            }
            let totalCantidad = 0, totalBase = 0, totalImpuestos = 0;
            orderlines.forEach(line => {
                if (line.is_reward_line) return;
                const qty = line.get_quantity();
                const unitPrice = line.get_unit_price();
                const baseLine = qty * unitPrice;
                totalBase += baseLine;
                totalCantidad += qty;
                (line.product.taxes_id || []).forEach(taxId => {
                    const tax = this.pos.taxes_by_id[taxId];
                    if (tax) totalImpuestos += baseLine * (tax.amount / 100);
                });
            });
            const totalPrecio = totalBase + totalImpuestos;
            const cumple = pricelistChangeRules.some(rule =>
                totalPrecio >= rule.minimum_amount && totalCantidad >= rule.minimum_qty
            );
            if (cumple) {
                const targetPricelistId = pricelistReward.reward.discount_max_amount;
                const targetPricelist = this.pos.pricelists.find(p => p.id === targetPricelistId);
                if (targetPricelist && (!this.pricelist || this.pricelist.id !== targetPricelistId)) {
                    this.set_pricelist(targetPricelist);
                    if (typeof this._resetTaxesAndPrices === 'function') this._resetTaxesAndPrices();
                }
            } else {
                this._restoreOriginalPricelist();
            }
        } else {
            this._restoreOriginalPricelist();
        }

        // Restaurar couponPointChanges para que _postPushOrderResolve los reciba
        // correctos y pueda llamar a confirm_coupon_programs con los datos completos.
        // Esto es lo que permite que se creen tarjetas nuevas y cupones de próxima compra.
        if (savedCouponPointChanges) {
            this.couponPointChanges = savedCouponPointChanges;
            _log("_updateRewards: couponPointChanges restaurados");
        }

        return superResult;
    },

    _restoreOriginalPrices(order) {
        if (!this._originalPrices || !Object.keys(this._originalPrices).length) return;
        const orderlines = order ? order.get_orderlines() :
            (this.pos && this.pos.get_order() ? this.pos.get_order().get_orderlines() : []);
        orderlines.forEach(line => {
            const lineUuid = line.uuid || line.cid;
            const orig = this._originalPrices[lineUuid];
            if (orig && orig.productId === line.product.id && line.get_unit_price() !== orig.price) {
                line.set_unit_price(orig.price);
            }
        });
        this._originalPrices = {};
    },

    _restoreOriginalPricelist() {
        if (!this._originalPricelistId) return;
        const original = this.pos.pricelists.find(p => p.id === this._originalPricelistId);
        if (original && this.pricelist?.id !== original.id) {
            this.set_pricelist(original);
            if (typeof this._resetTaxesAndPrices === 'function') this._resetTaxesAndPrices();
        }
        this._originalPricelistId = null;
    },
});

/**
 * CORRECCIÓN: push_single_order
 *
 * Solo garantizamos dos cosas:
 *
 * 1. Que coupon_point_changes llegue al payload del backend aunque otro módulo
 *    haya reemplazado export_as_JSON sin llamar a super.
 *
 * 2. Que la siguiente orden marque invalidCoupons = true para que fetchLoyaltyCard
 *    vaya al servidor a buscar el balance actualizado por confirm_coupon_programs,
 *    en lugar de usar el cache desactualizado.
 *
 * NO actualizamos couponCache aquí — eso lo hace _postPushOrderResolve de pos_loyalty
 * a través de confirm_coupon_programs, con los IDs definitivos del backend. Si lo
 * hiciéramos antes, los old_id de coupon_updates ya no coincidirían y la actualización
 * del cache en _postPushOrderResolve fallaría silenciosamente.
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
                _log("push_single_order: coupon_point_changes inyectado en payload");
            }
            return json;
        };

        let result;
        try {
            result = await super.push_single_order(...arguments);
        } finally {
            order.export_as_JSON = originalExport;
        }

        // Marcar la siguiente orden para que fetchLoyaltyCard vaya al servidor
        // en lugar de usar el cache — el balance real lo acaba de actualizar
        // confirm_coupon_programs en _postPushOrderResolve.
        if (result && hasPoints && this.selectedOrder) {
            this.selectedOrder.invalidCoupons = true;
            _log("push_single_order: invalidCoupons = true → próxima orden refetcheará desde backend");
        }

        return result;
    },
});
