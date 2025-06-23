/** @odoo-module */

import Widget from "@web/legacy/js/core/widget";
import { _t } from "@web/core/l10n/translation";
// var datepicker = require('web.datepicker');
import { jsonrpc } from "@web/core/network/rpc_service";
import IZIAutocomplete from "@izi_dashboard/js/component/general/izi_autocomplete";

import IZITags from "@izi_dashboard/js/component/general/izi_tags";
var IZISelectFilterTemp = Widget.extend({
    template: 'IZISelectFilterTemp',
    events: {
        'click .izi_select_field_filter_temp': '_onClickSelectFieldFilterTemp',
        'click .izi_select_dynamic_field_filter_temp': '_onClickSelectDynamicFieldFilterTemp',
        'click .dynamic_filter_button': '_onClickRemoveDynamicFilter',
        'click .izi_select_date_format': '_onClickSelectDateFormat',
        'click #izi_export_capture_analysis': '_onClickCaptureAnalysis',
        'click #izi_analysis_limit': '_onClickOpenLimitInput',
        'change #izi_limit_input_number': '_onChangeConfirmLimit',
        'keypress #izi_limit_input_number': '_onKeypressConfirmLimit',

        'click #izi_dynamic_filter_container_custom': '_onClickDynamicFilterCustom',
    },

    /**
     * @override
     */
    init: function (parent, $visual, args) {
        this._super.apply(this, arguments);
        
        this.parent = parent;
        this.$visual = $visual;
        this.analysis_id;
        if (args) {
            this.block_id = args.block_id;
            this.analysis_id = args.analysis_id;
        }
        this.filter_types = ['field_search', 'string_search', 'date_range', 'date_format'];
        this.$filter = {};
        this.filters;
        this.fields;
        this.dynamicFilter = [];
        this.dynamicFilterDescriptions = [];
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
        self.$btnExportCapture = self.$('#izi_export_capture_analysis');
        self.$btnExportLoading = self.$('#izi_export_capture_loading_analysis');

        // Filters
        self.filter_types.forEach(type => {
            self.$filter[type] = {};
            self.$filter[type].elm = self.$(`#izi_analysis_filter_temp_${type}`);
            self.$filter[type].field_id = false;
            self.$filter[type].field_name = false;
            self.$filter[type].values = [];
            self._initFilter(type);
        });
        self._generateFieldsOption()
    },

    /**
     * Private Method
     */
    _onClickDynamicFilterCustom:function(ev){
        var self = this
        var dynamicFilterCustom = self.$el.find('#izi_dynamic_filter_container_custom')
        var filter_elm = dynamicFilterCustom.find('#s2id_custom_dynamic_filter')
        filter_elm.select2('open')
    },
    _generateFieldsOption: function(ev){
        var self = this
        var dynamicFilterCustom = self.$el.find('#izi_dynamic_filter_container_custom')
        var filter_elm = dynamicFilterCustom.find(`#custom_dynamic_filter`)

        function checkAnalysisId() {
            if (typeof self.analysis_id !== 'undefined') {
                clearInterval(interval);
                var $dF = new IZIAutocomplete(self, {
                    elm: filter_elm,
                    multiple: false,
                    placeholder: "Select Field",
                    minimumInput: false,
                    isDynamic: true,
                    analysisId: self.analysis_id,
                    params: {
                        limit:10
                    },
                    onChange: function (id, name, value) {
                        if(id){
                            self._onClickSelectDynamicFieldFilterTemp(ev, value, name)
                        }
                    },
                });
            }
        }
        var interval = setInterval(checkAnalysisId, 100);
        
    },
    _generateChildFieldsOption: function(ev, args){
        var self = this;
        var dynamicFilterCustom = self.$el.find('#izi_dynamic_filter_container_custom')
        var filterElm = dynamicFilterCustom.find(`#custom_dynamic_filter_child`)
        if (self.analysis_id) {
            var filterParams = {
                'analysisId': self.analysis_id,
                'textField': args.field_name,
                'fields': ['id', args.field_name],
                'domain': [],
                'limit': 10,
                'modelFieldValues': 'field',
            }
            var $dF = new IZIAutocomplete(self, {
                elm: filterElm,
                multiple: false,
                placeholder: args.field_label,
                minimumInput: false,
                params: filterParams,
                fixPosition:true,
                onChange: function (id, name, value, label) {
                    if(id) {
                        self._checkDynamicFilterValues(args.field_name, value, name, args.field_label)
                    }
                },
            });
            var childElm = dynamicFilterCustom.find('#s2id_custom_dynamic_filter_child')
            childElm.select2('open')
        }
    },
    _initFilter: function(type) {
        var self = this;

        // String Search
        if (type == 'string_search') {
            self.$filter[type].elm.find('.izi_analysis_filter_temp_content').empty();
            self.$filter[type].elm.find('.izi_analysis_filter_temp_content').append('<input class="izi_select2"/>');
            self.$filter[type].values = [];
            new IZITags(self, {
                'elm': self.$filter[type].elm.find('.izi_select2'),
                'multiple': true,
                'placeholder': 'Values',
                'onChange': function(text, values) {
                    self.$filter[type].values = values;
                    self._checkFilterValues();
                },
            });
        }
        
        // DateRange
        if (type == 'date_range') {
            // self.$filter[type].elm.find('.izi_analysis_filter_temp_content').empty();
            self.$filter[type].values = [null, null];
            var $dateFromElm = self.$filter[type].elm.find('.izi_analysis_filter_temp_content').find('#izi_date_from');
            $dateFromElm.bootstrap_datepicker({
                language: "en",
                format: "yyyy-mm-dd",
                autoclose: true,
            });
            var $dateToElm = self.$filter[type].elm.find('.izi_analysis_filter_temp_content').find('#izi_date_to');
            $dateToElm.bootstrap_datepicker({
                language: "en",
                format: "yyyy-mm-dd",
                autoclose: true,
            });
            $dateFromElm.off('change');
            $dateFromElm.on('change', function (ev) {
                var newValue = ev.currentTarget.value ? moment(ev.currentTarget.value).format('YYYY-MM-DD') : null;
                if (self.$filter[type].values[0] != newValue) {
                    self.$filter[type].values[0] = newValue;
                    self._checkFilterValues();
                }
            });
            $dateToElm.off('change');
            $dateToElm.on('change', function (ev) {
                var newValue = ev.currentTarget.value ? moment(ev.currentTarget.value).format('YYYY-MM-DD') : null;
                if (self.$filter[type].values[1] != newValue) {
                    self.$filter[type].values[1] = newValue;
                    self._checkFilterValues();
                }
            });
            // var $dateFrom = new datepicker.DateWidget(self);
            // $dateFrom.appendTo(self.$filter[type].elm.find('.izi_analysis_filter_temp_content')).then((function () {
            //     // $dateFrom.setValue(moment(this.value));
            //     $dateFrom.$el.find('input').addClass('izi_input').attr('placeholder', 'Date From');
            //     $dateFrom.on('datetime_changed', self, function () {
            //         self.$filter[type].values[0] = $dateFrom.getValue() ? moment($dateFrom.getValue()).format('YYYY-MM-DD') : null;
            //         self._checkFilterValues();
            //     });
            // }));
            // var $dateTo = new datepicker.DateWidget(self);
            // $dateTo.appendTo(self.$filter[type].elm.find('.izi_analysis_filter_temp_content')).then((function () {
            //     // $dateTo.setValue(moment(this.value));
            //     $dateTo.$el.find('input').addClass('izi_input').attr('placeholder', 'Date To');
            //     $dateTo.on('datetime_changed', self, function () {
            //         self.$filter[type].values[1] = $dateTo.getValue() ? moment($dateTo.getValue()).format('YYYY-MM-DD') : null;
            //         self._checkFilterValues();
            //     });
            // }));
        }

        //Date Format
        if (type == 'date_format') {
            self.$filter[type].elm.find('.izi_analysis_filter_temp_content').empty();
            self.$filter[type].values = [];
            self.$filter[type].elm.find('.izi_analysis_filter_temp_content').append(`
                <div class="izi_dropdown izi_block_left izi_inline dropdown">
                    <button class="izi_m0 izi_py0 izi_pl0 izi_no_border dropdown-toggle" data-toggle="dropdown" type="button">
                        Select Date
                    </button>
                    <div class="dropdown-menu">
                        <a class="dropdown-item izi_select_date_format" data-date_format="yesterday">Yesterday</a>
                        <a class="dropdown-item izi_select_date_format" data-date_format="today">Today</a>
                        <a class="dropdown-item izi_select_date_format" data-date_format="this_week">This Week</a>
                        <a class="dropdown-item izi_select_date_format" data-date_format="this_month">This Month</a>
                        <a class="dropdown-item izi_select_date_format" data-date_format="this_year">This Year</a>
                        <a class="dropdown-item izi_select_date_format" data-date_format="mtd">Month to Date</a>
                        <a class="dropdown-item izi_select_date_format" data-date_format="ytd">Year to Date</a>
                        <a class="dropdown-item izi_select_date_format" data-date_format="last_week">Last Week</a>
                        <a class="dropdown-item izi_select_date_format" data-date_format="last_month">Last Month</a>
                        <a class="dropdown-item izi_select_date_format" data-date_format="last_two_months">Last 2 Months</a>
                        <a class="dropdown-item izi_select_date_format" data-date_format="last_three_months">Last 3 Months</a>
                        <a class="dropdown-item izi_select_date_format" data-date_format="last_year">Last Year</a>
                        <a class="dropdown-item izi_select_date_format" data-date_format="last_10">Last 10 Days</a>
                        <a class="dropdown-item izi_select_date_format" data-date_format="last_30">Last 30 Days</a>
                        <a class="dropdown-item izi_select_date_format" data-date_format="last_60">Last 60 Days</a>
                    </div>
                </div>
            `);
        }
    },
    _loadFilters: function(callback) {
        var self = this;
        if (self.analysis_id) {
            jsonrpc('/web/dataset/call_kw/izi.analysis/ui_get_filter_info', {
                model: 'izi.analysis',
                method: 'ui_get_filter_info',
                args: [self.analysis_id],
                kwargs: {},
            }).then(function (result) {
                if (result) {
                    self.filters = result.filters;
                    self.fields = result.fields;
                    // Add Filters
                    var unfiltered_types = self.filter_types;
                    self.filters.forEach(filter => {
                        self.$filter[filter.type].elm.addClass('active').attr('title', filter.name);
                        self.$filter[filter.type].field_id = filter.id;
                        self.$filter[filter.type].field_name = filter.field_name;
                        unfiltered_types = unfiltered_types.filter(function(e) { return e !== filter.type })
                    });
                    unfiltered_types.forEach(type => {
                        self.$filter[type].field_id = false;
                        self.$filter[type].field_name = false;
                        self.$filter[type].values = [];
                        self.$filter[type].elm.removeClass('active').attr('title', 'Select Filter');
                        self._initFilter(type);
                    });

                    // Add Fields
                    self.filter_types.forEach(type => {
                        if(type!=='field_search'){
                            self.$filter[type].elm.find('.izi_analysis_filter_temp_title .dropdown-menu').empty();
                            self.$filter[type].elm.find('.izi_analysis_filter_temp_title .dropdown-menu').append(`<a class="dropdown-item izi_select_field_filter_temp izi_col_transparent" data-type="${type}" data-id="-1">None</a>`);
                            self.fields[type].forEach(field => {
                                var activeClass = self.$filter[type].field_id == field.id ? 'active' : ''
                                var $elm = `
                                    <a class="dropdown-item izi_select_field_filter_temp ${activeClass}" data-type="${type}" data-id="${field.id}">${field.name}</a>
                                `;
                                self.$filter[type].elm.find('.izi_analysis_filter_temp_title .dropdown-menu').append($elm);
                            });
                        }else{
                            self.$filter[type].elm.find('.izi_analysis_filter_temp_title .dropdown-menu').empty();
                            self.$filter[type].elm.find('.izi_analysis_filter_temp_title .dropdown-menu').append(`<a class="dropdown-item izi_select_dynamic_field_filter_temp izi_col_transparent" data-type="${type}" data-id="-1">None</a>`);
                            self.fields[type].forEach(field => {
                                var activeClass = self.$filter[type].field_id == field.id ? 'active' : ''
                                var $elm = `
                                    <a class="dropdown-item izi_select_dynamic_field_filter_temp ${activeClass}" data-type="${type}" data-label="${field.name}" data-name="${field.field_name}">${field.name}</a>
                                `;
                                self.$filter[type].elm.find('.izi_analysis_filter_temp_title .dropdown-menu').append($elm);
                            });
                        }
                        
                    });

                    // Callback
                    if(callback) callback(result);
                }
            });
        }
    },
    _onClickRemoveDynamicFilter: function(ev) {
        var field = $(ev.currentTarget).data('filter-field')
        var self = this

        let filteredDynamicFilter = [];
        for (let i = 0; i < self.dynamicFilter.length; i++) {
            if (self.dynamicFilter[i][0] !== field) {
                filteredDynamicFilter.push(self.dynamicFilter[i]);
            }
        }
        self.dynamicFilter = filteredDynamicFilter;

        let filteredDynamicFilterDescription = [];
        for (let i = 0; i < self.dynamicFilterDescriptions.length; i++) {
            if (self.dynamicFilterDescriptions[i][0] !== field) {
                filteredDynamicFilterDescription.push(self.dynamicFilterDescriptions[i]);
            }
        }
        self.dynamicFilterDescriptions = filteredDynamicFilterDescription;

        if(self.$visual){
            var filter_values = []
            self.dynamicFilter.forEach(filter => {
                filter_values.push(filter)
            });

            self.filter_types.forEach(type => {
                if (self.$filter[type].field_name && self.$filter[type].values && self.$filter[type].values.length) {
                    filter_values.push([self.$filter[type].field_name, type, self.$filter[type].values]);
                }
            });

            var args = {}
            var visual = self.$visual
            if(visual.drilldown_history && visual.drilldown_history.length > 0){
                var drilldownHistory = visual.drilldown_history
                args = drilldownHistory[drilldownHistory.length - 1]
            }
            args['filter_temp_values'] = filter_values
            args['filters'] = args['drilldown_filters']

            visual._getDataAnalysis(args, function (result) {
                if (visual.parent && visual.parent.$title)
                visual.parent.$title.html(visual.analysis_name + visual.drilldown_title);
                visual.temp_analysis_data = result.data;
                visual._makeChart(result,true)
                // Trigger Insights On Config Analysis
                if (visual.parent && visual.parent.parent && visual.parent.parent.$configAnalysis && visual.parent.parent.$configAnalysis.onInsight) {
                    visual.parent.parent.$configAnalysis._generateInsights();
                }
            })
            self._fillSelectedDynamicFilter()
        }
        if (self.dynamicFilter.length == 0){
            self.el.querySelector('#izi_dynamic_filter_container_custom').className = 'izi_analysis_filter_temp'
        }
    },
    _onClickSelectDynamicFieldFilterTemp: function(ev, name, label) {
        var self = this;
        var field_name = ""
        var field_label = ""
        if(name && label){
            // field_name = name;
            field_name = name
            field_label = label;
        }else{
            field_name = $(ev.currentTarget).data('name');
            field_label = $(ev.currentTarget).data('label');
        }
        if (self.analysis_id && field_name) {
            var args = {
                'field_label': field_label,
                'field_name': field_name
            }
            self.$el.find(`#custom_dynamic_filter`).select2('val','');
            self._generateChildFieldsOption(ev,args)

        }
    },
    _checkDynamicFilterValues: function(field_name, field_values, field_values_name, field_label) {
        var self = this;
        var double_run = false; //ga ngerti kenapa select2 ngerun double. terpaksa pakai cara ini mas hehe..
        if (self.$visual && field_name && field_values && field_values_name) {
            var appendDynamic = true
            for (let i = 0; i < self.dynamicFilter.length; i++) {
                let filter = self.dynamicFilter[i];
                if (filter[0] == field_name && filter[1] == 'string_search') {
                    if(!filter[2].includes(field_values)){
                        self.dynamicFilterDescriptions[i][1].push(field_values_name)
                        filter[2].push(field_values);
                    }else{
                        double_run = true
                    }
                    appendDynamic = false;
                    break;
                }
            }
            if (appendDynamic == true){
                self.dynamicFilterDescriptions.push([field_name,[field_values_name],field_label])
                self.dynamicFilter.push([field_name,'string_search',[field_values]])
            }
            var filter_values = []
            self.dynamicFilter.forEach(filter => {
                filter_values.push(filter)
            });

            self.filter_types.forEach(type => {
                if (self.$filter[type].field_name && self.$filter[type].values && self.$filter[type].values.length) {
                    filter_values.push([self.$filter[type].field_name, type, self.$filter[type].values]);
                }
            });

            var args = {}
            var visual = self.$visual
            if(visual.drilldown_history && visual.drilldown_history.length > 0){
                var drilldownHistory = visual.drilldown_history
                args = drilldownHistory[drilldownHistory.length - 1]
            }
            args['filter_temp_values'] = filter_values
            args['filters'] = args['drilldown_filters']
            if (!double_run){
                visual._getDataAnalysis(args, function (result) {
                    if (visual.parent && visual.parent.$title && visual.analysis_name)
                    visual.parent.$title.html(visual.analysis_name + visual.drilldown_title);
                    visual.temp_analysis_data = result.data;
                    visual._makeChart(result,true)
                    // Trigger Insights On Config Analysis
                    if (visual.parent && visual.parent.parent && visual.parent.parent.$configAnalysis && visual.parent.parent.$configAnalysis.onInsight) {
                        visual.parent.parent.$configAnalysis._generateInsights();
                    }
                    if(visual.drilldown_history.length == 0){
                        visual.$el.find('.izi_reset_drilldown').hide();
                        visual.$el.find('.izi_drillup').hide();
                    }
                })
            }
            self._fillSelectedDynamicFilter()
        }
    },
    _fillSelectedDynamicFilter: function(){
        var self = this
        self.el.querySelector('#izi_dynamic_filter_container_custom').className = 'izi_analysis_filter_temp active'

        var element = self.el.querySelector('#izi_selected_dynamic_filter')
        element.innerHTML=""
        for (let i = 0; i < self.dynamicFilter.length; i++) {
            let filter = self.dynamicFilter[i];
            var name = self.dynamicFilterDescriptions[i]
            const button = document.createElement('button')
            button.className = 'dynamic_filter_button';
            button.setAttribute('data-filter-field', filter[0]);
            button.setAttribute('data-filter-value', filter[2]); 
            button.innerHTML = `
                `+ name[2] +` | `+ name[1] +` <span class="close-btn">X</span>
            `
            element.appendChild(button)
        }
    },
    _onClickSelectFieldFilterTemp: function(ev) {
        var self = this;
        var type = $(ev.currentTarget).data('type');
        var field_id = $(ev.currentTarget).data('id');
        var name = $(ev.currentTarget).text();
        if (self.analysis_id && field_id && type) {
            jsonrpc('/web/dataset/call_kw/izi.analysis/ui_add_filter_temp_by_field', {
                model: 'izi.analysis',
                method: 'ui_add_filter_temp_by_field',
                args: [self.analysis_id, field_id, type],
                kwargs: {},
            }).then(function (result) {
                self._loadFilters(function(result) {
                    self._checkFilterValues();
                });
                self._initFilter(type);
            })
        }
    },
    _changeLimit: function() {
        var self = this;
        var args = self.$visual.last_drilldown_args;
        if (!args){
            args={};
        }
        var limit_value = parseInt(self.el.querySelector('#izi_limit_input_number').value)
        if(limit_value>0){
            args['drilldown_limit'] = limit_value
        }
        self.$visual._getDataAnalysis(args, function (result) {
            if (self.$visual.parent && self.$visual.parent.$title)
            self.$visual.parent.$title.html(self.$visual.analysis_name + self.$visual.drilldown_title);
            self.$visual.temp_analysis_data = result.data;
            self.$visual._makeChart(result);
            // if(show_popup==true){
            //     self.$visual._customWizardPopup(result)
            // }
            if(self.$visual.drilldown_title){
                self.$visual.$el.find('.izi_reset_drilldown').show();
                self.$visual.$el.find('.izi_drillup').show();
            }

            // Trigger Insights On Config Analysis
            if (self.$visual.parent && self.$visual.parent.parent && self.$visual.parent.parent.$configAnalysis && self.$visual.parent.parent.$configAnalysis.onInsight) {
                self.$visual.parent.parent.$configAnalysis._generateInsights();
            }
        })
    },
    _onChangeConfirmLimit: function(ev) {
        var self = this;
        ev.preventDefault();
        // self._changeLimit();
    },
    _onKeypressConfirmLimit: function(ev) {
        var self = this;
        if (ev.key === "Enter") {
            ev.preventDefault();
            self._changeLimit();
        }
    },
    _onClickOpenLimitInput: function(ev) {
        var self = this
        var input_element = self.el.querySelector('#izi_limit_input').style.display
        if (input_element == 'none'){
            self.el.querySelector('#izi_limit_input').style.display = 'block';
            self.$('#izi_analysis_filter_temp_limit').addClass('active');
        }else{
            self.el.querySelector('#izi_limit_input').style.display = 'none';
            self.$('#izi_analysis_filter_temp_limit').removeClass('active');
        }
    },
    _onClickSelectDateFormat: function(ev) {
        var self = this;
        self.$filter['date_format'].values[0] = $(ev.currentTarget).data('date_format');
        var text = $(ev.currentTarget).text();
        self.$filter['date_format'].elm.find('.izi_analysis_filter_temp_content .dropdown-toggle').text(text);
        self._checkFilterValues();
    },
    _onClickCaptureAnalysis: function (ev) {
        var self = this;
        self.$btnExportCapture.hide();
        self.$btnExportLoading.show();

        ev.stopPropagation();
            var btn = $(self).button('loading');
            var blockId = $(ev.currentTarget).closest('.izi_dashboard_block_item').attr('data-id');
            var querySelector = document.querySelector('.izi_view_analysis .izi_dashboard_block_item');
            if (blockId) {
                querySelector = document.querySelector(`.izi_dashboard_block_item[data-id="${blockId}"]`);
            }
            html2canvas(querySelector, {useCORS: true, allowTaint: false}).then(function(canvas){
                window.jsPDF = window.jspdf.jsPDF;
                var img = canvas.toDataURL("image/jpeg", 0.90);
                var doc = new jsPDF("l", "px", [canvas.width, canvas.height]);
                doc.addImage(img,'JPEG', 0, 0, canvas.width, canvas.height, 'FAST');
                doc.save($('.izi_title').text() + '.pdf');
                new swal('Success', `Analysis has been Captured.`, 'success');
                btn.button('reset');

                self.$btnExportCapture.show();
                self.$btnExportLoading.hide();
            });
    },

    _checkFilterValues: function() {
        var self = this;
        var filter_temp_values = [];
        self.filter_types.forEach(type => {
            if (self.$filter[type].field_name && self.$filter[type].values && self.$filter[type].values.length) {
                filter_temp_values.push([self.$filter[type].field_name, type, self.$filter[type].values]);
            } 
        });

        self.dynamicFilter.forEach(function (filter) {
            filter_temp_values.push(filter);
        });

        if (self.$visual && filter_temp_values) {
            var args = {}
            var visual = self.$visual
            if(visual.drilldown_history && visual.drilldown_history.length > 0){
                var drilldownHistory = visual.drilldown_history
                args = drilldownHistory[drilldownHistory.length - 1]
            }
            args['filter_temp_values'] = filter_temp_values


            visual._getDataAnalysis(args, function (result) {
                if (visual.parent && visual.parent.$title)
                visual.parent.$title.html(visual.analysis_name + visual.drilldown_title);
                visual.temp_analysis_data = result.data;
                visual._makeChart(result,true)
                // Trigger Insights On Config Analysis
                if (visual.parent && visual.parent.parent && visual.parent.parent.$configAnalysis && visual.parent.parent.$configAnalysis.onInsight) {
                    visual.parent.parent.$configAnalysis._generateInsights();
                }
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

export default IZISelectFilterTemp;