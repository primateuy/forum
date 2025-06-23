/** @odoo-module */

import { renderToElement } from "@web/core/utils/render";
import { _t } from "@web/core/l10n/translation";
import { jsonrpc } from "@web/core/network/rpc_service";
import IZIDialog from "@izi_dashboard/js/component/general/izi_dialog";
import { useService } from "@web/core/utils/hooks";

var IZISelectDashboard = IZIDialog.extend({
    template: 'IZISelectDashboard',
    events: {
        'click .izi_select_dashboard_item': '_onSelectDashboardItem',
        'click .izi_new_dashboard_item': '_onClickNewDashboardWizard',
        'click .izi_edit_dashboard_item': '_onClickEditDashboardWizard',
        'click .izi_dialog_bg': '_onClickBackground',
        'keydown .izi_search_dashboard_name': '_onKeyupDashboardName',
        'click .izi_search_dashboard_category .dropdown-item': '_onClickSearchCategory',
    },

    /**
     * @override
     */
    init: function (parent, $content) {
        this._super.apply(this, arguments);

        this.parent = parent;
        this.$content = $content;
        this.allDashboards = [];
        this.selectedDashboard;
        this.keyword;
        this.typingTimer;
        this.doneTypingInterval = 500;
        this.selectedCategory;
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
        
        self.$dashboardContainer = self.$el.find('.izi_select_dashboard_item_container');
        self.$btnSearchCategory = self.$el.find('.izi_search_dashboard_category');
        self._loadDashboardItems();
        self._loadCategories();
    },

    /**
     * Private Method
     */
        _loadDashboardItems: function (selectDashboard=false) {
        var self = this;
        var keywordType = self.keyword ? self.keyword : "";
        let args = ""
        if (self.selectedCategory) {
            args = [['category_id', '=', self.selectedCategory]];
        } else {
            args = [];
        }
        self.$dashboardContainer.empty();
        jsonrpc('/web/dataset/call_kw/izi.dashboard/search_read', {
            model: 'izi.dashboard',
            method: 'search_read',
            args: [args, ['id', 'name', 'write_date', 'theme_name', 'date_format', 'start_date', 'end_date', 'table_name', 'category_id', 'use_sidebar']],
            kwargs: {},
        }).then(function (results) {
            self.allDashboards = results;
            // New Dashboard
            var $new = `
            <div class="izi_new_dashboard_item izi_select_item izi_select_item_blue">
                <div class="izi_title" t-esc="name">New Dashboard</div>
                <div class="izi_subtitle" t-esc="source_table">
                    Create new dashboard
                </div>
                <div class="izi_select_item_icon">
                    <span class="material-icons">add</span>
                </div>
            </div>
            `;
            self.$dashboardContainer.append($new);

            var filteredDashboard = self.allDashboards.filter(function (el)
            {
                return el.name.toLowerCase().includes(keywordType.toLowerCase());
            });

            // Render Dashboard Item
            filteredDashboard.forEach(dashboard => {
                var $content = $(renderToElement('IZISelectDashboardItem', {
                    name: `${dashboard.name}`,
                    id: dashboard.id,
                    write_date: moment(dashboard.write_date).format('LLL'),
                    theme_name: `${dashboard.theme_name}`,
                    category: dashboard.category_id[1]
                }));
                self.$dashboardContainer.append($content);
            });
        })
    },
    _loadCategories: function () {
        var self = this;
        self.$btnSearchCategory.find('.dropdown-menu').empty();
        self.$btnSearchCategory.find('.dropdown-menu').append(`
            <a class="dropdown-item" data-id="0" data-title="All Groups">
                All Groups
            </a>
        `)
        jsonrpc('/web/dataset/call_kw/izi.dashboard.category/search_read', {
            model: 'izi.dashboard.category',
            method: 'search_read',
            args: [[], ['id', 'name']],
            kwargs: {},
        }).then(function (results) {
            // console.log('Query', results);
            results.forEach(res => {
                self.$btnSearchCategory.find('.dropdown-menu').append(`
                    <a class="dropdown-item" data-id="${res.id}" data-title="${res.name}">
                        ${res.name}
                    </a>
                `)
            })
        });
    },
    _onClickSearchCategory: function(ev) {
        var self = this;
        var id = $(ev.currentTarget).data('id');
        var text = $(ev.currentTarget).data('title');
        this.selectedCategory = id;
        self._loadDashboardItems();
        self.$btnSearchCategory.find('.dropdown-toggle .title').text(text);
    },
    _onClickBackground: function (ev) {
        var self = this;
        this._super.apply(this, arguments);
    },
    _onKeyupDashboardName: function(ev) {
        var self = this;
        var keyword = $(ev.currentTarget).val();
        if (self.typingTimer)
            clearTimeout(self.typingTimer);
        self.keyword = keyword;
        self.typingTimer = setTimeout(function() {
            self._loadDashboardItems();
        }, self.doneTypingInterval);
    },
    _onSelectDashboardItem: function (ev) {
        var self = this;
        var id = $(ev.currentTarget).data('id');
        var name = $(ev.currentTarget).data('name');
        self.selectedDashboard = id;
        console.log(self)
        self.allDashboards.forEach(dashboard => {
            if (dashboard.id == id) {
                self.parent._selectDashboard(id, name, dashboard.write_date, dashboard.theme_name, dashboard.date_format, dashboard.start_date, dashboard.end_date, dashboard.use_sidebar);
                // if (self.parent && self.parent.$viewDashboard && self.parent.$viewDashboard.$viewDashboardAskContainer)
                //     self.parent.$viewDashboard.$viewDashboardAskContainer.find('.izi_view_dashboard_ask_header_table span').text(dashboard.table_name || 'Undefined');
            }
        });
        self.destroy();
    },

    _onClickEditDashboardWizard: function(ev) {
        ev.stopPropagation();
        var self = this;
        var $parent = $(ev.currentTarget).closest('.izi_select_dashboard_item');
        var id = $parent.data('id');
        self.selectedDashboard = id;
        if (self.selectedDashboard) {
            self._getOwl().action.doAction({
                type: 'ir.actions.act_window',
                name: _t('Dashboard'),
                target: 'new',
                res_id: self.selectedDashboard,
                res_model: 'izi.dashboard',
                views: [[false, 'form']],
                context: { 'active_test': false },
            },{
                onClose: function(){
                    self._loadDashboardItems();
                },
            });
        }
    },
    
    _onClickNewDashboardWizard: function(ev) {
        ev.stopPropagation();
        var self = this;
        self._getOwl().action.doAction({
            type: 'ir.actions.act_window',
            name: _t('Dashboard'),
            target: 'new',
            res_id: false,
            res_model: 'izi.dashboard',
            views: [[false, 'form']],
            context: { 'active_test': false },
        },{
            onClose: function(){
                self._loadDashboardItems();
            },
        });
    },
    _onClickNewDashboard: function(ev) {
        var self = this;
        new swal({
            title: "Confirmation",
            text: `
                Do you confirm to create a new dashboard? After create a dashboard, \
                you can add an analysis from analysis menu.
            `,
            icon: "info",
            showCancelButton: true,
            confirmButtonText: 'Yes',
            heightAuto : false,
        }).then((result) => {
            if (result.isConfirmed) {
                var name = 'Untitled Dashboard';
                jsonrpc('/web/dataset/call_kw/izi.dashboard/create', {
                    model: 'izi.dashboard',
                    method: 'create',
                    args: [{
                        'name': name,
                    }],
                    kwargs: {},
                }).then(function (result) {
                    if (result) {
                        new swal('Success', `Your dashboard has been created successfully.`, 'success');
                        // self.parent._selectDashboard(result, name, moment.utc().format('YYYY-MM-DD HH:mm:ss z'));
                        self.destroy();
                    } else {
                        new swal('Failed', 'There is an error while creating the dashboard', 'error');
                    }
                });
            }
        });
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

export default IZISelectDashboard;