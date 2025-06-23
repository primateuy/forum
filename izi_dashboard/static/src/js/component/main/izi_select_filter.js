/** @odoo-module */

import Widget from "@web/legacy/js/core/widget";
import { renderToElement } from "@web/core/utils/render";
import { jsonrpc } from "@web/core/network/rpc_service";

var IZISelectFilter = Widget.extend({
    template: 'IZISelectFilter',
    events: {
        'click .izi_select_filter_item': '_onSelectFilter',
    },

    /**
     * @override
     */
    init: function (parent) {
        this._super.apply(this, arguments);

        this.parent = parent;
        this.fields = [];
    },

    willStart: function () {
        var self = this;

        return this._super.apply(this, arguments).then(function () {
            return self.load();
        });
    },

    load: function () {
        var self = this;
    },

    start: function () {
        var self = this;
        this._super.apply(this, arguments);
        // Add Content
        if (self.parent.selectedAnalysis) {
            jsonrpc('/web/dataset/call_kw/izi.analysis/ui_get_analysis_info', {
                model: 'izi.analysis',
                method: 'ui_get_analysis_info',
                args: [self.parent.selectedAnalysis],
                kwargs: {},
            }).then(function (result) {
                // console.log('Get Filters', result)
                self.fields = result.fields_for_filters;
                self.fields.forEach(field => {
                    var $content = $(renderToElement('IZISelectFilterItem', {
                        name: field.name,
                        id: field.id,
                        field_type: field.field_type,
                        field_icon: IZIFieldIcon.getIcon(field.field_type),
                        filter_operators: result.filter_operators,
                    }));
                    self.$el.append($content)
                });
            })
        }
    },

    /**
     * Private Method
     */
    _onSelectFilter: function (ev) {
        var self = this;
        var field_id = $(ev.currentTarget).data('id');
        var logical_operator = $('#select_form_filter_' + field_id).find('#select_condition_' + field_id).val();
        var operator_id = $('#select_form_filter_' + field_id).find('#select_operator_' + field_id).val();
        var value = $('#select_form_filter_' + field_id).find('#select_value_' + field_id).val();
        if (self.parent.selectedAnalysis) {
            var data = {
                'field_id': field_id,
                'operator_id': operator_id,
                'condition': logical_operator,
                'value': value,
            }
            jsonrpc('/web/dataset/call_kw/izi.analysis/ui_add_filter_by_field', {
                model: 'izi.analysis',
                method: 'ui_add_filter_by_field',
                args: [self.parent.selectedAnalysis, data],
                kwargs: {},
            }).then(function (result) {
                self.parent._loadAnalysisInfo();
                self.parent._onClickAddFilter();
                self.parent._renderVisual();
            })
        }
    },
    
    _getOwl: function() {
        var cur_obj = this;
        while (cur_obj) {
            if (cur_obj.__owl__) {
                return cur_obj;
            }
            cur_obj = cur_obj.parent;
        }
        return undefined;
    },
});

export default IZISelectFilter;