/** @odoo-module */

import Widget from "@web/legacy/js/core/widget";
import { renderToElement } from "@web/core/utils/render";
import { jsonrpc } from "@web/core/network/rpc_service";

var IZISelectSort = Widget.extend({
    template: 'IZISelectSort',
    events: {
        'click .izi_select_sort_item': '_onSelectSort',
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

    start: function() {
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
                // console.log('Get Sorts', result)
                self.fields = result.fields_for_sorts;
                self.fields.forEach(field => {
                    var $content = $(renderToElement('IZISelectSortItem', {
                        name: field.name,
                        id: field.id,
                        field_type: field.field_type,
                        field_icon: IZIFieldIcon.getIcon(field.field_type),
                    }));
                    self.$el.append($content)
                });
            })
        }
    },

    /**
     * Private Method
     */
    _onSelectSort: function(ev) {
        var self = this;
        var field_id = $(ev.currentTarget).data('id');
        if (self.parent.selectedAnalysis) {
            jsonrpc('/web/dataset/call_kw/izi.analysis/ui_add_sort_by_field', {
                model: 'izi.analysis',
                method: 'ui_add_sort_by_field',
                args: [self.parent.selectedAnalysis, field_id],
                kwargs: {},
            }).then(function (result) {
                self.parent._loadAnalysisInfo();
                self.parent._onClickAddSort();
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

export default IZISelectSort;