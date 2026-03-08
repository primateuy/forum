/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { _t } from '@web/core/l10n/translation';
import { Order, Orderline } from '@point_of_sale/app/store/models';
import { RewardButton } from '@pos_loyalty/app/control_buttons/reward_button/reward_button';

const DEBUG = false;

function log(msg, data) {
    if (DEBUG && typeof console !== 'undefined' && console.log) {
        console.log('[cambio_precio_safe]', msg, data || '');
    }
}

function convertPythonDomainToJSON(pythonDomain) {
    if (!pythonDomain || pythonDomain === '[]' || pythonDomain === '') {
        return [];
    }
    let jsonDomain = pythonDomain.replace(/'/g, '"');
    jsonDomain = jsonDomain.replace(/\(/g, '[').replace(/\)/g, ']');
    jsonDomain = jsonDomain.replace(/\bTrue\b/g, 'true');
    jsonDomain = jsonDomain.replace(/\bFalse\b/g, 'false');
    jsonDomain = jsonDomain.replace(/\bNone\b/g, 'null');
    return jsonDomain;
}

function evaluateSimpleDomain(domain, record) {
    if (!domain || domain === '[]' || domain === '') {
        return true;
    }
    let parsedDomain;
    try {
        parsedDomain = typeof domain === 'string' ? JSON.parse(convertPythonDomainToJSON(domain)) : domain;
    } catch (error) {
        console.error('[cambio_precio_safe] Error parseando dominio:', domain, error);
        return false;
    }
    if (!Array.isArray(parsedDomain) || parsedDomain.length === 0) {
        return true;
    }
    for (const condition of parsedDomain) {
        if (!Array.isArray(condition) || condition.length < 3) {
            continue;
        }
        const [field, operator, value] = condition;
        let fieldValue = record[field];
        if (Array.isArray(fieldValue) && fieldValue.length >= 1 && !Array.isArray(value)) {
            fieldValue = fieldValue[0];
        }
        switch (operator) {
            case '=':
            case '==':
                if (fieldValue != value) {
                    return false;
                }
                break;
            case '!=':
                if (fieldValue == value) {
                    return false;
                }
                break;
            case '>':
                if (!(fieldValue > value)) {
                    return false;
                }
                break;
            case '>=':
                if (!(fieldValue >= value)) {
                    return false;
                }
                break;
            case '<':
                if (!(fieldValue < value)) {
                    return false;
                }
                break;
            case '<=':
                if (!(fieldValue <= value)) {
                    return false;
                }
                break;
            case 'in':
                if (Array.isArray(fieldValue)) {
                    if (!fieldValue.some((v) => value.includes(v))) {
                        return false;
                    }
                } else if (!Array.isArray(value) || !value.includes(fieldValue)) {
                    return false;
                }
                break;
            case 'not in':
                if (Array.isArray(fieldValue)) {
                    if (fieldValue.some((v) => value.includes(v))) {
                        return false;
                    }
                } else if (Array.isArray(value) && value.includes(fieldValue)) {
                    return false;
                }
                break;
            case 'like':
            case 'ilike':
                if (!String(fieldValue || '').toLowerCase().includes(String(value || '').toLowerCase())) {
                    return false;
                }
                break;
            default:
                return false;
        }
    }
    return true;
}

function getRewardIdentifier(reward) {
    return String(reward.id || reward.reward_id || reward.uuid || reward.program_id || reward.description || '');
}

function getSelectedCustomReward(order, rewardType) {
    const values = Object.values(order._customRewardState || {});
    return values.find((value) => value && value.reward_type === rewardType) || null;
}

patch(Orderline.prototype, {
    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        if (this.reward_label) {
            json.reward_label = this.reward_label;
        }
        if (this.reward_type) {
            json.reward_type = this.reward_type;
        }
        if (this.reward_badge_color) {
            json.reward_badge_color = this.reward_badge_color;
        }
        if (this._original_unit_price !== undefined) {
            json._original_unit_price = this._original_unit_price;
        }
        return json;
    },

    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        this.reward_label = json.reward_label || null;
        this.reward_type = json.reward_type || null;
        this.reward_badge_color = json.reward_badge_color || null;
        this._original_unit_price = json._original_unit_price;
    },

    get_full_product_name() {
        const originalName = super.get_full_product_name(...arguments);
        if (this.reward_label && this.reward_type === 'fixed_price') {
            return `${originalName} - PRECIO FIJO`;
        }
        return originalName;
    },

    getDisplayName() {
        return this.get_full_product_name();
    },
});

patch(Order.prototype, {
    setup() {
        super.setup(...arguments);
        this._customRewardState = this._customRewardState || {};
    },

    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        if (this._customRewardState && Object.keys(this._customRewardState).length) {
            json._custom_reward_state = this._customRewardState;
        }
        return json;
    },

    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        this._customRewardState = json._custom_reward_state || {};
    },

    _clearFixedPriceLabels() {
        for (const line of this.get_orderlines()) {
            if (line.reward_type === 'fixed_price') {
                line.reward_label = null;
                line.reward_type = null;
                line.reward_badge_color = null;
            }
        }
    },

    _restoreFixedPriceLines() {
        for (const line of this.get_orderlines()) {
            if (line._original_unit_price !== undefined) {
                line.set_unit_price(line._original_unit_price);
                delete line._original_unit_price;
            }
            if (line.reward_type === 'fixed_price') {
                line.reward_label = null;
                line.reward_type = null;
                line.reward_badge_color = null;
            }
        }
    },

    _applyFixedPriceRewardConfig(reward) {
        this._restoreFixedPriceLines();
        this._clearFixedPriceLabels();

        const fixedPrice = reward.fixed_price;
        const rulesProductDomains = reward.rules_product_domains || [];
        if (!(fixedPrice > 0)) {
            return;
        }

        for (const line of this.get_orderlines()) {
            if (line.is_reward_line) {
                continue;
            }
            const matches = !rulesProductDomains.length || rulesProductDomains.some((ruleDomain) => {
                return evaluateSimpleDomain(ruleDomain.product_domain, line.product);
            });
            if (!matches) {
                continue;
            }
            if (line._original_unit_price === undefined) {
                line._original_unit_price = line.get_unit_price();
            }
            line.set_unit_price(fixedPrice);
            line.reward_label = reward.reward_label || '[Precio Fijo]';
            line.reward_type = 'fixed_price';
            line.reward_badge_color = reward.reward_badge_color || 'success';
        }
    },

    _reapplyCustomRewards() {
        const fixedPriceReward = getSelectedCustomReward(this, 'fixed_price');
        if (fixedPriceReward) {
            this._applyFixedPriceRewardConfig(fixedPriceReward);
        } else {
            this._restoreFixedPriceLines();
        }

        const pricelistReward = getSelectedCustomReward(this, 'pricelist_change');
        if (pricelistReward && pricelistReward.pricelist_id) {
            const pricelistId = Array.isArray(pricelistReward.pricelist_id)
                ? pricelistReward.pricelist_id[0]
                : pricelistReward.pricelist_id;
            const pricelist = this.pos.pricelists.find((pl) => pl.id === pricelistId);
            if (pricelist && this.pricelist?.id !== pricelist.id) {
                this.set_pricelist(pricelist);
                if (typeof this._resetTaxesAndPrices === 'function') {
                    this._resetTaxesAndPrices();
                }
            }
        }
    },

    add_product(product, options) {
        const result = super.add_product(...arguments);
        this._reapplyCustomRewards();
        return result;
    },

    removeOrderline(line) {
        const result = super.removeOrderline(...arguments);
        this._reapplyCustomRewards();
        return result;
    },

    set_pricelist(pricelist) {
        const result = super.set_pricelist(...arguments);
        const selectedPricelistReward = getSelectedCustomReward(this, 'pricelist_change');
        if (selectedPricelistReward) {
            const rewardPricelistId = Array.isArray(selectedPricelistReward.pricelist_id)
                ? selectedPricelistReward.pricelist_id[0]
                : selectedPricelistReward.pricelist_id;
            if (pricelist?.id !== rewardPricelistId) {
                for (const [key, value] of Object.entries(this._customRewardState || {})) {
                    if (value.reward_type === 'pricelist_change') {
                        delete this._customRewardState[key];
                    }
                }
            }
        }
        return result;
    },
});

patch(RewardButton.prototype, {
    async _applyReward(reward, couponId, potentialQty) {
        if (reward.reward_type === 'pricelist_change' || reward.reward_type === 'fixed_price') {
            return await this._applyCustomReward(reward, couponId, potentialQty);
        }
        return await super._applyReward(...arguments);
    },

    async _applyCustomReward(reward, couponId, potentialQty) {
        const order = this.pos.get_order();
        if (!order) {
            return false;
        }

        order._customRewardState = order._customRewardState || {};
        const rewardKey = getRewardIdentifier(reward);

        if (reward.reward_type === 'pricelist_change') {
            if (!reward.pricelist_id) {
                this.notification.add(_t('La recompensa no tiene lista de precios configurada.'), { type: 'danger' });
                return false;
            }
            const pricelistId = Array.isArray(reward.pricelist_id) ? reward.pricelist_id[0] : reward.pricelist_id;
            const pricelist = this.pos.pricelists.find((pl) => pl.id === pricelistId);
            if (!pricelist) {
                this.notification.add(_t('La lista de precios de la recompensa no está cargada en el POS.'), { type: 'danger' });
                return false;
            }
            // Solo una recompensa activa de cambio de lista por orden.
            for (const [key, value] of Object.entries(order._customRewardState)) {
                if (value.reward_type === 'pricelist_change' && key !== rewardKey) {
                    delete order._customRewardState[key];
                }
            }
            order._customRewardState[rewardKey] = {
                reward_type: 'pricelist_change',
                reward_id: reward.id,
                pricelist_id: reward.pricelist_id,
                label: reward.reward_label || reward.description || reward.name,
                coupon_id: couponId || null,
            };
            order.set_pricelist(pricelist);
            if (typeof order._resetTaxesAndPrices === 'function') {
                order._resetTaxesAndPrices();
            }
            order._reapplyCustomRewards();
            log('Aplicada recompensa pricelist_change', reward);
            return true;
        }

        if (reward.reward_type === 'fixed_price') {
            order._customRewardState[rewardKey] = {
                reward_type: 'fixed_price',
                reward_id: reward.id,
                fixed_price: reward.fixed_price,
                rules_product_domains: reward.rules_product_domains || [],
                reward_label: reward.reward_label || '[Precio Fijo]',
                reward_badge_color: reward.reward_badge_color || 'success',
                coupon_id: couponId || null,
                potentialQty: potentialQty || null,
            };
            order._applyFixedPriceRewardConfig(order._customRewardState[rewardKey]);
            log('Aplicada recompensa fixed_price', reward);
            return true;
        }

        return false;
    },
});
