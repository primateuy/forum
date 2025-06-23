/** @odoo-module */

import Widget from "@web/legacy/js/core/widget";
import { _t } from "@web/core/l10n/translation";
import { jsonrpc } from "@web/core/network/rpc_service";
import { useService } from "@web/core/utils/hooks";

function isQuarter(value) {
    const quarterPattern = /^Q[1-4] \d{4}$/;
    return quarterPattern.test(value);
};
function isWeek(value) {
    const weekPattern = /^W[0-9]{1,2} \d{4}$/;
    return weekPattern.test(value);
};

var IZIViewVisual = Widget.extend({
    template: 'IZIViewVisual',
    events: {
        'click .izi_reset_drilldown': '_onClickResetDrilldown',
        'click .izi_drillup': '_onClickDrillup',
    },

    /**
     * @override
     */
    init: function (parent, args) {
        this._super.apply(this, arguments);
        this.interval;
        this.parent = parent;
        this.context = false;
        if (parent && parent.context) {
            this.context = parent.context;
        }
        this.grid;
        this.index = 0;
        this.mode;
        this.visual_type_name;
        this.rtl;
        this.dimension_alias;
        this.drilldown_level = 0;
        this.drilldown_title = '';
        this.max_drilldown_level;
        this.action_id;
        this.action_external_id;
        this.analysis_name;
        this.field_by_alias = {};
        this.model_field_names = [];
        this.analysis_data;
        this.ask_chart;
        this.temp_analysis_data;
        this.drilldown_wait;
        this.drilldown_history = [];
        this.last_drilldown_args;
        this.dynamicFilters = [];
        this.field_type_by_alias = {};
        if (args) {
            this.block_id = args.block_id;
            this.analysis_id = args.analysis_id;
            this.filters = JSON.parse(JSON.stringify(args.filters || {}));
            this.refresh_interval = args.refresh_interval;
            this.index = args.index;
            this.mode = args.mode;
            this.visual_type_name = args.visual_type_name;
            this.rtl = args.rtl;
            this.analysis_data = args.analysis_data;
            this.ask_chart = args.ask_chart;
        }
        am4core.options.autoDispose = false;
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
        var args = {}
        if (self.filters) {
            args.filters = self.filters;
            args.mode = self.mode;
        }
        self._renderVisual(args);
        if (self.refresh_interval && self.refresh_interval >= 10) {
            var readyInterval = true;
            self.interval = setInterval(function () {
                if (readyInterval) {
                    readyInterval = false;
                    if (self.last_drilldown_args) {
                        args.mode = self.last_drilldown_args.drilldown_mode;
                        args.filters = self.last_drilldown_args.drilldown_filters;
                        args.drilldown_title = self.last_drilldown_args.drilldown_title;
                        args.drilldown_level = self.last_drilldown_args.drilldown_level;
                        args.drilldown_field = self.last_drilldown_args.drilldown_field;
                        args.drilldown_field_subtype = self.last_drilldown_args.drilldown_field_subtype;
                    }
                    self._renderVisual(args, function() {
                        readyInterval = true;
                        if (args.drilldown_level > 0) {
                            self.$el.find('.izi_reset_drilldown').show();
                            self.$el.find('.izi_drillup').show();
                        }
                    });
                }
            }, self.refresh_interval * 1000);
        }
        self.drilldown_wait = false;
    },

    /**
     * Called By Others
     */
    _setAnalysisId: function (analysis_id) {
        var self = this;
        self.analysis_id = analysis_id;
    },

    _renderVisual: function (args, callback) {
        var self = this;
        self._deleteVisual();
        if(args && args['filter_temp_values']){
            self.dynamicFilters = args['filter_temp_values']
        }else{
            self.dynamicFilters = []
        }
        am4core.options.autoDispose = false;
        if (self.analysis_id) {
            self._getDataAnalysis(args, function (result) {
                setTimeout(function() {
                    if (self.parent && self.parent.$title)
                        self.parent.$title.html(self.analysis_name);
                    self.temp_analysis_data = result.data;
                    self._makeChart(result);
                    if (callback) {
                        callback();
                    }
                }, Math.floor(self.index/6)*500);
            })
        } else if (self.analysis_data) {
            self._makeChart(self.analysis_data);
            if (callback) {
                callback();
            }
        }
    },

    tableToLocaleString: function(table_data) {
        var new_table_data = []
        table_data.forEach(t_data => {
            var new_t_data = []
            t_data.forEach(dt => {
                if (typeof dt == 'number')
                    dt = dt.toLocaleString()
                new_t_data.push(dt);
            });
            new_table_data.push(new_t_data);
        });
        return new_table_data;
    },
    _getSlideViewVisualByAnalysisId: function(analysis_id){
        var self = this
        var selected_visual = self
        if(self.slide_visuals.length>0){
            
            self.slide_visuals.forEach(vis => {
                if(vis.analysis_id == analysis_id){
                    selected_visual = vis
                }
            })
        }
        return selected_visual
    },
    _getViewVisualByAnalysisId: function(analysis_id) {
        var self = this;
        if (self.parent && self.parent._getViewVisualByAnalysisId)
            return self.parent._getViewVisualByAnalysisId(analysis_id);
        return false;
    },

    _onClickDrillup: function (ev) {
        var self = this
        self.drilldown_level = self.drilldown_level - 1;
        var title = self.drilldown_title
        var last_drilldown_title = title.lastIndexOf('/');
        var new_title = title.substring(0, last_drilldown_title);
        self.drilldown_title = new_title
        var history = self.drilldown_history
        var key = history.length - 2
        var args = {}
        if (self.drilldown_history.length>1){
            if (self.filters)
                self.filters = history[key].drilldown_filters
            args = {
                'mode': history[key].drilldown_mode,
                'filters': history[key].drilldown_filters,
                'drilldown_level': history[key].drilldown_level,
                'drilldown_field': history[key].drilldown_field,
                'drilldown_field_subtype': history[key].drilldown_field_subtype
            };
            // self.filters = history[key].drilldown_filters
            if (self.dynamicFilters){
                args['filter_temp_values'] = self.dynamicFilters
            }
            history.pop();
            self.last_drilldown_args = args;
            self._getDataAnalysis(args, function (result) {
                if (self.parent && self.parent.$title)
                self.parent.$title.html(self.analysis_name + self.drilldown_title);
                self.temp_analysis_data = result.data;
                self._makeChart(result,true)
                // Trigger Insights On Config Analysis
                if (self.parent && self.parent.parent && self.parent.parent.$configAnalysis && self.parent.parent.$configAnalysis.onInsight) {
                    self.parent.parent.$configAnalysis._generateInsights();
                }
            })

        }else{
            self._onClickResetDrilldown()
        }

    },
    _onClickResetDrilldown: function (ev) {
        var self = this;
        self.drilldown_history = []
        self.drilldown_level = 0;
        self.drilldown_title = '';
        if (self.filters)
            self.filters.action = [];
        var args = {}
        if (self.filters) {
            args.filters = self.filters;
            args.mode = self.mode;
        }
        if (self.dynamicFilters){
            args['filter_temp_values'] = self.dynamicFilters
        }
        self.last_drilldown_args = args;
        self._getDataAnalysis(args, function (result) {
            if (self.parent && self.parent.$title)
            self.parent.$title.html(self.analysis_name);
            self.temp_analysis_data = result.data;
            if(self.is_slide){
                self._makeChartSlide(result)
            }else{
                self._makeChart(result,true)
            }
            // Trigger Insights On Config Analysis
            if (self.parent && self.parent.parent && self.parent.parent.$configAnalysis && self.parent.parent.$configAnalysis.onInsight) {
                self.parent.parent.$configAnalysis._generateInsights();
            }
        })
        self.$el.find('.izi_reset_drilldown').hide();
        self.$el.find('.izi_drillup').hide();
    },

    _onHitChart: function (ev, visual, val) {
        var analysis_id = false;
        var self = false;
        var is_slide = visual.is_slide
        if (ev.target && ev.target.htmlContainer) {
            if(is_slide){
                analysis_id = parseInt($(ev.target.htmlContainer).closest('.visual-chart').data('analysis_id'));
            }else{
                analysis_id = parseInt($(ev.target.htmlContainer).closest('.izi_view_visual').data('analysis_id'));
            }
            if (analysis_id && visual) {
                // Visual From On Hit Listener Is Wrong
                // So We Get The Right One By Searching With Analysis Id
                if(is_slide){
                    visual = visual._getSlideViewVisualByAnalysisId(analysis_id)
                }else{
                    visual = visual._getViewVisualByAnalysisId(analysis_id)
                }
                self = visual;
                 
                if (self && self.dimension_alias && val && !self.drilldown_wait) {
                    self.drilldown_wait = true;
                    const existing_drilldown_fields = document.querySelector('.drilldown_background');
                    if (existing_drilldown_fields) {
                        existing_drilldown_fields.remove();
                    }
                    const drilldown_fields = document.createElement('div');
                    const drilldown_background = document.createElement('div');
                    drilldown_background.className="drilldown_background"
                    drilldown_background.appendChild(drilldown_fields)
                    
                    const top_position = ev.point.y
                    const left_position = ev.point.x

                    const drilldown_header = `
                        <div class="drilldown-fields-header" style="border-bottom: 1px solid #eee;width: 100%;height: 30px;display: flex;align-items: center;justify-content: space-between;">
                            <div class="ps-2 fw-bolder" style="font-size: 12px;">
                                Select Field
                            </div>
                            <div class="">
                                <span id="close_drilldown_menu" class="btn btn-outline-secondary text-muted" style="border: 0;">
                                    <span class="material-icons" style="font-size: 14px;display: flex;">close</span>
                                </span>
                            </div>
                        </div>
                    `;
                    drilldown_fields.innerHTML = drilldown_header;
                    
                    drilldown_fields.style.top = `${top_position}px`;
                    drilldown_fields.style.left = `${left_position}px`;
                    
                    drilldown_fields.className = 'drilldown-fields';
                    
                    const close_btn = drilldown_fields.querySelector("#close_drilldown_menu");
                    close_btn.addEventListener('click', () => {
                        drilldown_background.remove();
                    });
                    drilldown_background.addEventListener('click', () => {
                        drilldown_background.remove();
                    });
                    const drilldown_fields_menus = document.createElement('div');
                    drilldown_fields_menus.className = 'drilldown-fields-menus';
                    drilldown_fields.appendChild(drilldown_fields_menus);

                    jsonrpc('/web/dataset/call_kw/izi.analysis/ui_get_available_fields', {
                        model: 'izi.analysis',
                        method: 'ui_get_available_fields',
                        args: [[analysis_id], {}],
                        kwargs: {},
                    }).then(function (data) {
                        var show_popup = data[0]
                        var res = data[1]
                        res.forEach(item => {
                            const menu_item = document.createElement('div');
                            menu_item.className = 'drilldown-fields-item';
                            menu_item.textContent = item.name;
                            menu_item.setAttribute('field-id', item.id);
                            menu_item.addEventListener('click', () => {
                                if (self.drilldown_level == 0){
                                    if (!self.filters){
                                        self.filters = {};
                                    }
                                    self.filters.action = [];
                                }
                                self.drilldown_level += 1;

                                // if (!self.filters)
                                //     self.filters = {};
                                if (!self.filters.action) {
                                    self.filters.action = [];
                                }
                                var field_by_alias = []
                                if (self.field_by_alias) {
                                    field_by_alias = self.field_by_alias
                                }
                                var field_type_by_alias = []
                                if (self.field_type_by_alias) {
                                    field_type_by_alias = self.field_type_by_alias
                                }
                                if (self.dimension_alias in field_by_alias && self.dimension_alias in field_type_by_alias) {
                                    var field_name = self.field_by_alias[self.dimension_alias];
                                    var field_type = self.field_type_by_alias[self.dimension_alias];
                                    var additional_action_filters = [[field_name, '=', val[self.dimension_alias]]];
                                    if (['date', 'datetime'].includes(field_type)) {
                                        additional_action_filters = self._formatDomains(field_name, '=', val[self.dimension_alias]);
                                    }
                                    additional_action_filters.forEach(additional_action_filter => {
                                        self.filters.action.push({
                                            'field_name': additional_action_filter[0],
                                            'operator': additional_action_filter[1],
                                            'value': additional_action_filter[2],
                                        });
                                    });
                                }
                                var args = {
                                    'mode': self.mode,
                                    'filters': self.filters || {},
                                    'drilldown_level': self.drilldown_level,
                                    'drilldown_field': false,
                                };
                                if (self.dynamicFilters){
                                    args['filter_temp_values'] = self.dynamicFilters
                                }
                                self.drilldown_title += ' / ' + val[self.dimension_alias];
                                args.drilldown_field = item.field_name
                                args.drilldown_field_subtype = item.field_subtype
                                const curr_filter = JSON.parse(JSON.stringify(self.filters));
                                var drilldown_history = {
                                    'drilldown_mode': self.mode,
                                    'drilldown_title': self.drilldown_title,
                                    'drilldown_filters': curr_filter,
                                    'drilldown_level': self.drilldown_level,
                                    'drilldown_field': item.field_name,
                                    'drilldown_field_subtype': item.field_subtype
                                }
                                self.drilldown_history.push(drilldown_history)
                                self.last_drilldown_args = args
                                self._getDataAnalysis(args, function (result) {
                                    if (self.parent && self.parent.$title)
                                    self.parent.$title.html(self.analysis_name + self.drilldown_title);
                                    self.temp_analysis_data = result.data;
                                    if(is_slide){
                                        self._makeChartSlide(result);
                                        self.$el.parent().find('.izi_reset_drilldown').show();
                                        self.$el.parent().find('.izi_drillup').show();
                                    }else{
                                        self._makeChart(result);
                                        self.$el.find('.izi_reset_drilldown').show();
                                        self.$el.find('.izi_drillup').show();
                                    }
                                    if(show_popup==true){
                                        self._customWizardPopup(result)
                                    }

                                    // Trigger Insights On Config Analysis
                                    if (self.parent && self.parent.parent && self.parent.parent.$configAnalysis && self.parent.parent.$configAnalysis.onInsight) {
                                        self.parent.parent.$configAnalysis._generateInsights();
                                    }
                                });
                                drilldown_background.remove();
                            });
                            drilldown_fields_menus.appendChild(menu_item);
                        });
                        
                        document.body.appendChild(drilldown_background);

                        const rect = drilldown_fields.getBoundingClientRect();
                        const viewportHeight = window.innerHeight;
                        if (rect.bottom > viewportHeight) {
                            const newTopPosition = top_position - (rect.bottom - viewportHeight) - 10;
                            drilldown_fields.style.top = `${newTopPosition}px`;
                        }else{
                        }
                        self.drilldown_wait = false;
                    })
                } else if (false) {
                    // Open Action
                    if (self.action_model && self.drilldown_level > self.max_drilldown_level) {
                        jsonrpc('/web/dataset/call_kw/izi.analysis/ui_get_view_parameters', {
                            model: 'izi.analysis',
                            method: 'ui_get_view_parameters',
                            args: [[analysis_id], args],
                            kwargs: {},
                        }).then(function (res) {
                            if (res) {
                                var data = res;
                                if (data.model) {
                                    self._getOwl().action.doAction({
                                        type: 'ir.actions.act_window',
                                        name: data.name,
                                        res_model: data.model,
                                        views: [[false, "list"], [false, "form"]],
                                        view_type: 'list',
                                        view_mode: 'list',
                                        target: 'current',
                                        context: {},
                                        domain: data.domain,
                                    });
                                }
                                // } else {
                                //     new swal('Failed', 'Analysis must have model and domain first to open the list view!', 'error');
                                // }
                            }
                        })
                    }
                }
            }
        }
        
    },

    _convertDomainToUTC(domain, callback) {
        var self = this;
        if (self.analysis_id) {
            jsonrpc('/web/dataset/call_kw/izi.analysis/convert_domain_to_utc', {
                model: 'izi.analysis',
                method: 'convert_domain_to_utc',
                args: [self.analysis_id, domain],
                kwargs: {},
            }).then(function (result) {
                if (callback) {
                    callback(result);
                }
            })
        }
    },

    // _formatDomains: function (field_name, operator, value) {
    //     var self = this;

    //     // store original locale
    //     var originalLocale = moment.locale();

    //     // set locale to english
    //     moment.locale('en');

    //     var start_date = null;
    //     var end_date = null;

    //     if (moment(value, 'DD MMM YYYY', true).isValid()) {
    //         start_date = moment(value, 'DD MMM YYYY', true).format('YYYY-MM-DD');
    //         end_date = moment(value, 'DD MMM YYYY', true).add(1, 'd').format('YYYY-MM-DD');
    //     } else if (moment(value, 'DD MMMM YYYY', true).isValid()) {
    //         start_date = moment(value, 'DD MMMM YYYY', true).format('YYYY-MM-DD');
    //         end_date = moment(value, 'DD MMMM YYYY', true).add(1, 'M').format('YYYY-MM-DD');
    //     } else if (moment(value, 'MMM YYYY', true).isValid()) {
    //         start_date = moment(value, 'MMM YYYY', true).format('YYYY-MM-DD');
    //         end_date = moment(value, 'MMM YYYY', true).add(1, 'M').format('YYYY-MM-DD');
    //     } else if (moment(value, 'MMMM YYYY', true).isValid()) {
    //         start_date = moment(value, 'MMMM YYYY', true).format('YYYY-MM-DD');
    //         end_date = moment(value, 'MMMM YYYY', true).add(1, 'M').format('YYYY-MM-DD');
    //     } else if (moment(value, 'YYYY', true).isValid()) {
    //         start_date = moment(value, 'YYYY', true).format('YYYY-MM-DD');
    //         end_date = moment(value, 'YYYY', true).add(1, 'Y').format('YYYY-MM-DD');
    //     } else if (isQuarter(value)) {
    //         // In Case Of Quarter Format: Q1 2023
    //         var values = value.split(' ');
    //         var quarter = values[0].split('Q')[1];
    //         var year = values[1];
    //         start_date = moment().quarter(quarter).year(year).startOf('quarter').format('YYYY-MM-DD');
    //         end_date = moment().quarter(quarter).year(year).endOf('quarter').add(1, 'd').format('YYYY-MM-DD');
    //     } else if (isWeek(value)) {
    //         // In Case Of Week Format: W21 2023
    //         var values = value.split(' ');
    //         var week = values[0].split('W')[1];
    //         var year = values[1];
    //         // Moment Starts Week From Sunday
    //         start_date = moment().week(week).year(year).startOf('week').add(1, 'd').format('YYYY-MM-DD');
    //         end_date = moment().week(week).year(year).endOf('week').add(2, 'd').format('YYYY-MM-DD');
    //     }

    //     // set back original locale
    //     moment.locale(originalLocale);

    //     if (start_date != null && end_date != null) {
    //         return [[field_name, '>=', start_date], [field_name, '<', end_date]];
    //     } else {
    //         return [[field_name, operator || '=', value]];
    //     }
    // },
    _formatDomains: function (field_name, operator, value) {
        var self = this;

        // store original locale
        var originalLocale = moment.locale();

        var start_date = null;
        var end_date = null;
         
        // R : untuk arab, masih kena, udah sampai saya update moment month untuk arab, masih ga bisa ke handle
        if (moment(value, 'DD MMM YYYY', true).isValid()) {
            var parsed_date = moment(value, 'DD MMM YYYY', true);
            moment.locale('en');
            start_date = parsed_date.format('YYYY-MM-DD');
            end_date = parsed_date.add(1, 'd').format('YYYY-MM-DD');
        } else if (moment(value, 'DD MMMM YYYY', true).isValid()) {
            var parsed_date = moment(value, 'DD MMMM YYYY', true);
            moment.locale('en');
            start_date = parsed_date.format('YYYY-MM-DD');
            end_date = parsed_date.add(1, 'M').format('YYYY-MM-DD');
        } else if (moment(value, 'MMM YYYY', true).isValid()) {
            var parsed_date = moment(value, 'MMM YYYY', true);
            moment.locale('en');
            start_date = parsed_date.format('YYYY-MM-DD');
            end_date = parsed_date.add(1, 'M').format('YYYY-MM-DD');
        } else if (moment(value, 'MMMM YYYY', true).isValid()) {
            var parsed_date = moment(value, 'MMMM YYYY', true);
            moment.locale('en');
            start_date = parsed_date.format('YYYY-MM-DD');
            end_date = parsed_date.add(1, 'M').format('YYYY-MM-DD');
        } else if (moment(value, 'YYYY', true).isValid()) {
            var parsed_date = moment(value, 'YYYY', true);
            moment.locale('en');
            start_date = parsed_date.format('YYYY-MM-DD');
            end_date = parsed_date.add(1, 'Y').format('YYYY-MM-DD');
        } else if (isQuarter(value)) {
            // In Case Of Quarter Format: Q1 2023
            var values = value.split(' ');
            var quarter = values[0].split('Q')[1];
            var year = values[1];
            start_date = moment().quarter(quarter).year(year).startOf('quarter').format('YYYY-MM-DD');
            end_date = moment().quarter(quarter).year(year).endOf('quarter').add(1, 'd').format('YYYY-MM-DD');
        } else if (isWeek(value)) {
            // In Case Of Week Format: W21 2023
            var values = value.split(' ');
            var week = values[0].split('W')[1];
            var year = values[1];
            // Moment Starts Week From Sunday
            start_date = moment().week(week).year(year).startOf('week').add(1, 'd').format('YYYY-MM-DD');
            end_date = moment().week(week).year(year).endOf('week').add(2, 'd').format('YYYY-MM-DD');
        }

        // set back original locale
        moment.locale(originalLocale);

        if (start_date != null && end_date != null) {
            return [[field_name, '>=', start_date], [field_name, '<', end_date]];
        } else {
            return [[field_name, operator || '=', value]];
        }
    },
    _makeChartSlide: function(result,show_drill_button = false) {
        var self = this;
        var chart;
        var visual;
        var el = self.$el

        var visual_type = result.visual_type;
        var data = result.data;
        var table_data = result.values;
        var columns = result.fields;

        var idElm = `visual_`+self.analysis_id;
        el.attr('id', idElm);
        el.attr('data-analysis_id', self.analysis_id);
        if ($(`#${idElm}`).length == 0) return false;
        // If Error
        if (result.is_error) {
            visual = new amChartsComponent({
                title: "Error",
                idElm: idElm,
            });
            chart = visual.showError(idElm, result.error || 'Unknown error, check the log');
            return chart;
        }

        // If Not Error
        self.dimension_alias = result.dimensions[0];
        visual = new amChartsComponent({
            title: "Visual",
            idElm: idElm,
            data: data,
            dimension: result.dimensions[0],
            metric: result.metrics,
            visual: self,
            callback: self._onHitChart,
            
            prefix_by_field: result.prefix_by_field,
            suffix_by_field: result.suffix_by_field,
            decimal_places_by_field: result.decimal_places_by_field,
            is_metric_by_field: result.is_metric_by_field,
            locale_code_by_field: result.locale_code_by_field,

            scorecardStyle: result.visual_config_values.scorecardStyle,
            scorecardIcon: result.visual_config_values.scorecardIcon,
            backgroundColor: result.visual_config_values.backgroundColor,
            borderColor: result.visual_config_values.borderColor,
            fontColor: result.visual_config_values.fontColor,
            scorecardIconColor: result.visual_config_values.scorecardIconColor,
            legendPosition: result.visual_config_values.legendPosition,
            legendHeatmap: result.visual_config_values.legendHeatmap,
            area: result.visual_config_values.area,
            stacked: result.visual_config_values.stacked,
            innerRadius: result.visual_config_values.innerRadius,
            circleType: result.visual_config_values.circleType,
            labelSeries: result.visual_config_values.labelSeries,

            labelBullet: result.visual_config_values.labelBullet,
            numberFormat: result.visual_config_values.numberFormat,
            numberFormatValues: result.custom_number_format_values,
            showAxisValue: result.visual_config_values.showAxisValue,

            rotateLabel: result.visual_config_values.rotateLabel,
            scrollBar: result.visual_config_values.scrollBar,
            currency_code: result.visual_config_values.currency_code,
            particle: result.visual_config_values.particle,
            trends: result.visual_config_values.trends,
            trendLine: result.visual_config_values.trendLine,
            mapView: result.visual_config_values.mapView,
        });
        if (visual_type == 'custom') {
            if (result.use_render_visual_script && result.render_visual_script) {
                try {
                    eval(result.render_visual_script);
                } catch (error) {
                    new swal('Render Visual Script: JS Error', error.message, 'error')
                }
            }
        }
        else if (visual_type == 'iframe') {
            if (result.visual_config_values.iframeHTMLTag || result.visual_config_values.iframeURL) {
                // console.log('Render Iframe', result.visual_config_values.iframeHTMLTag, result.visual_config_values.iframeURL);
                try {
                    if (result.visual_config_values.iframeHTMLTag) {
                        $(`#${idElm}`).append(result.visual_config_values.iframeHTMLTag);
                    } else if (result.visual_config_values.iframeURL) {
                        $(`#${idElm}`).append(`<iframe src="${result.visual_config_values.iframeURL}" style="width:100%;height:100%;border:none;"></iframe>`);
                    }
                } catch (error) {
                    new swal('Render Iframe: JS Error', error.message, 'error')
                }
            }
        }
        else if (visual_type == 'table') {
            columns = self.formatTableColumns(result);
            if (!self.grid) {
                self.grid = new gridjs.Grid({
                    columns: columns,
                    data: table_data,
                    sort: true,
                    pagination: true,
                    resizable: true,
                    // search: true,
                    className: {
                        table: `gridjs-table-${idElm}`,
                    }
                }).render($(`#${idElm}`).get(0));
                self.renderSumTableRow(result, table_data, `gridjs-table-${idElm}`);
            } else {
                self.grid.updateConfig({
                    columns: columns,
                    data: table_data,
                }).forceRender();
                self.renderSumTableRow(result, table_data, `gridjs-table-${idElm}`);
            }
        }
        else if (visual_type == 'pie') {
            chart = visual.makePieChart();
        }
        else if (visual_type == 'radar') {
            chart = visual.makeRadarChart();
        }
        else if (visual_type == 'flower') {
            chart = visual.makeFlowerChart();
        }
        else if (visual_type == 'radialBar') {
            chart = visual.makeRadialBarChart();
        }
        else if (visual_type == 'bar') {
            chart = visual.makeBarChart();
        }
        else if (visual_type == 'row') {
            chart = visual.makeRowChart();
        }
        else if (visual_type == 'bullet_bar') {
            chart = visual.makeBulletBarChart();
        }
        else if (visual_type == 'bullet_row') {
            chart = visual.makeBulletRow();
        }
        else if (visual_type == 'row_line') {
            chart = visual.makeRowLine();
        }
        else if (visual_type == 'bar_line') {
            chart = visual.makeBarLineChart();
        }
        else if (visual_type == 'line') {
            chart = visual.makeLineChart();
        }
        else if (visual_type == 'scatter') {
            chart = visual.makeScatterChart();
        }
        else if (visual_type == 'heatmap_geo') {
            chart = visual.makeHeatmapGeo();
        }
        else if (visual_type == 'scrcard_basic') {

            if ((self.el.id).indexOf('block') === -1) { // layout ketika di preview chart
                self.$el.parents(".izi_dashboard_block_item").addClass("izi_dashboard_block_item_v_background");
                self.$el.parent().addClass('izi_view_background');
                self.$el.addClass('izi_view_scrcard_container');
            }else{ // layout ketika di block Dashboard 
                self.$el.parents(".izi_dashboard_block_item").find(".izi_dashboard_block_title").text("");
                self.$el.parents(".izi_dashboard_block_item").find(".izi_dashboard_block_header").addClass("izi_dashboard_block_btn_config");                    
            }
            visual.makeScorecardBasic();
        }
        else if (visual_type == 'scrcard_trend') {

            if ((self.el.id).indexOf('block') === -1) { // layout ketika di preview chart
                self.$el.parents(".izi_dashboard_block_item").addClass("izi_dashboard_block_item_v_background");
                self.$el.parent().addClass('izi_view_background');
                self.$el.addClass('izi_view_scrcard_container');
            }else{ // layout ketika di block Dashboard 
                self.$el.parents(".izi_dashboard_block_item").find(".izi_dashboard_block_title").text("");
                self.$el.parents(".izi_dashboard_block_item").find(".izi_dashboard_block_header").addClass("izi_dashboard_block_btn_config");                    
            }
            visual.makeScorecardTrend();
        }
        else if (visual_type == 'scrcard_progress') {

            if ((self.el.id).indexOf('block') === -1) { // layout ketika di preview chart
                self.$el.parents(".izi_dashboard_block_item").addClass("izi_dashboard_block_item_v_background");
                self.$el.parent().addClass('izi_view_background');
                self.$el.addClass('izi_view_scrcard_container');
            }else{ // layout ketika di block Dashboard 
                self.$el.parents(".izi_dashboard_block_item").find(".izi_dashboard_block_title").text("");
                self.$el.parents(".izi_dashboard_block_item").find(".izi_dashboard_block_header").addClass("izi_dashboard_block_btn_config");                    
            }
            visual.makeScorecardProgress();
        }
        var style=''
        if(show_drill_button){
            style='style="display:block;"'
        }
        // Drill Up
        self.$el.find('.izi_reset_drilldown').remove();
        self.$el.append(`
        <button class="btn btn-sm btn-primary izi_reset_drilldown" `+ style +`>
        <i class="fa fa-chevron-up"></i>
        </button>
        `);

        // One step drill up
        self.$el.find('.izi_drillup').remove();
        self.$el.append(`
            <button class="btn btn-sm btn-primary izi_drillup" `+ style +`>
                <i class="fa fa-arrow-left"></i>
            </button>
        `);
    },
    _makeChart: function (result,show_drill_button = false) {
        var self = this;
        var chart;
        var visual;

        // Not Elegant
        self.$el.parent().removeClass('izi_view_background');
        self.$el.removeClass('izi_view_scrcard_container scorecard scorecard-sm');
        self.$el.parents(".izi_dashboard_block_item").removeClass("izi_dashboard_block_item_v_background");

        var visual_type = result.visual_type;
        if(visual_type == "odooView"){
            self._makeOdooView(result)
        }else{
            var data = result.data;
            var table_data = result.values;
            var columns = result.fields;
    
            var idElm = `visual_${self.analysis_id}`;
            if (self.block_id) {
                idElm = `block_${self.block_id}_${idElm}`;
            }
            self.$el.attr('style', '');
            self.$el.attr('id', idElm);
            self.$el.attr('data-analysis_id', self.analysis_id);
            if ($(`#${idElm}`).length == 0) return false;
            // If Error
            if (result.is_error) {
                visual = new amChartsComponent({
                    title: self.analysis_name,
                    idElm: idElm,
                });
                chart = visual.showError(idElm, result.error || 'Unknown error, check the log');
                return chart;
            }
    
            // If Not Error
            self.dimension_alias = result.dimensions[0];
            visual = new amChartsComponent({
                title: self.analysis_name,
                idElm: idElm,
                data: data,
                dimension: result.dimensions[0],
                metric: result.metrics,
                visual: self,
                callback: self._onHitChart,
                
                prefix_by_field: result.prefix_by_field,
                suffix_by_field: result.suffix_by_field,
                decimal_places_by_field: result.decimal_places_by_field,
                is_metric_by_field: result.is_metric_by_field,
                locale_code_by_field: result.locale_code_by_field,
    
                scorecardStyle: result.visual_config_values.scorecardStyle,
                scorecardIcon: result.visual_config_values.scorecardIcon,
                backgroundColor: result.visual_config_values.backgroundColor,
                borderColor: result.visual_config_values.borderColor,
                fontColor: result.visual_config_values.fontColor,
                scorecardIconColor: result.visual_config_values.scorecardIconColor,
                legendPosition: result.visual_config_values.legendPosition,
                legendHeatmap: result.visual_config_values.legendHeatmap,
                area: result.visual_config_values.area,
                stacked: result.visual_config_values.stacked,
                innerRadius: result.visual_config_values.innerRadius,
                circleType: result.visual_config_values.circleType,
                labelSeries: result.visual_config_values.labelSeries,
                labelBullet: result.visual_config_values.labelBullet,

                numberFormat: result.visual_config_values.numberFormat,
                numberFormatValues: result.custom_number_format_values,
                showAxisValue: result.visual_config_values.showAxisValue,
                
                rotateLabel: result.visual_config_values.rotateLabel,
                scrollBar: result.visual_config_values.scrollBar,
                currency_code: result.visual_config_values.currency_code,
                particle: result.visual_config_values.particle,
                trends: result.visual_config_values.trends,
                trendLine: result.visual_config_values.trendLine,
                mapView: result.visual_config_values.mapView,
            });
            if (visual_type == 'custom') {
                if (result.use_render_visual_script && result.render_visual_script) {
                    let visual_script = result.render_visual_script
                    let visual_script_css = result.render_visual_script_css || ''
                    if(visual_script_css){
                        visual_script_css = visual_script_css.replace("#idElm", "#${idElm}");
                        visual_script_css = visual_script_css.replace(/#idElm/g, "#${idElm}");
                        visual_script_css = '\n$(`#${idElm}`).append(`<style>\n'+ visual_script_css +'\n</style>`);';
                    }
                    let combined_visual_script = visual_script_css + visual_script
                    try {
                        // eval(result.render_visual_script);
                        eval(combined_visual_script);
                    } catch (error) {
                        new swal('Render Visual Script: JS Error', error.message, 'error')
                    }
                }
            }
            else if (visual_type == 'iframe') {
                if (result.visual_config_values.iframeHTMLTag || result.visual_config_values.iframeURL) {
                    try {
                        if (result.visual_config_values.iframeHTMLTag) {
                            $(`#${idElm}`).append(result.visual_config_values.iframeHTMLTag);
                        } else if (result.visual_config_values.iframeURL) {
                            $(`#${idElm}`).append(`<iframe src="${result.visual_config_values.iframeURL}" style="width:100%;height:100%;border:none;"></iframe>`);
                        }
                    } catch (error) {
                        new swal('Render Iframe: JS Error', error.message, 'error')
                    }
                }
            }
            else if (visual_type == 'table') {
                columns = self.formatTableColumns(result);
                let wrapper = '';
                let tableSearchbox = result.visual_config_values.tableSearchbox;
                let tableHeight = result.visual_config_values.tableHeight;
                let tableLines = result.visual_config_values.tableLines;
                let tableWrapText = result.visual_config_values.tableWraptext ? 'normal' : 'nowrap';

                // Cek apakah idElm mengandung "block"
                if (idElm.includes("block")) {
                    $(`#${idElm}`).append(`<div class="izi_table_container"></div>`);
                    wrapper = ' .izi_table_container';
                }
                $(`#${idElm}${wrapper}`).empty();

                // Jika grid sudah ada, update config saja
                if (self.grid && !idElm.includes("block")) {
                    self.grid.updateConfig({
                        columns: columns,
                        data: table_data,
                        search: tableSearchbox,
                        height: `${tableHeight}px`,
                        pagination: { limit: tableLines },
                        style: { table: { 'white-space': tableWrapText } }
                    }).forceRender();
                } else {
                    $(`#${idElm}${wrapper}`).empty();
                    // Jika grid belum ada, buat baru
                    self.grid = new gridjs.Grid({
                        columns: columns,
                        data: table_data,
                        sort: true,
                        pagination: true,
                        fixedHeader: true,
                        search: tableSearchbox,
                        height: `${tableHeight}px`,
                        pagination: { limit: tableLines },
                        style: { table: { 'white-space': tableWrapText } },
                        className: { table: `gridjs-table-${idElm}` }
                    }).render($(`#${idElm}${wrapper}`).get(0));
                }

                // Render ulang sum row
                self.renderSumTableRow(result, table_data, `gridjs-table-${idElm}`);


            //     columns = self.formatTableColumns(result);
            //     let wrapper = '';
            //     let tableSearchbox = result.visual_config_values.tableSearchbox;
            //     let tableHeight = result.visual_config_values.tableHeight;
            //     let tableLines = result.visual_config_values.tableLines;
            //     let tableWrapText = result.visual_config_values.tableWraptext ? 'normal' : 'nowrap';

            //     if (idElm.includes("block")) {
            //         $(`#${idElm}`).append(`
            //             <div class="izi_table_container"></div>
            //         `);
            //         wrapper = ' .izi_table_container'
            //     }
            //     $(`#${idElm}${wrapper}`).empty();

            //     if (!self.grid) {
            //         self.grid = new gridjs.Grid({
            //             columns: columns,
            //             data: table_data,
            //             sort: true,
            //             pagination: true,
            //             // resizable: true, //Not working, when fixedHeader is true
            //             fixedHeader: true,
                        
            //             search: tableSearchbox,
            //             height: `${tableHeight}px`,
            //             pagination: {
            //                 limit: tableLines,
            //             },
            //             style: { 
            //                 table: { 
            //                     'white-space': tableWrapText
            //                 }
            //             },
            //             className: {
            //                 table: `gridjs-table-${idElm}`,
            //             }
            //         }).render($(`#${idElm}${wrapper}`).get(0));
            //         self.renderSumTableRow(result, table_data, `gridjs-table-${idElm}`);
            //     } else {
            //         self.grid.updateConfig({
            //             columns: columns,
            //             data: table_data,
            //         }).forceRender();
            //         self.renderSumTableRow(result, table_data, `gridjs-table-${idElm}`);
            //     }
            }
            else if (visual_type == 'pie') {
                chart = visual.makePieChart();
            }
            else if (visual_type == 'radar') {
                chart = visual.makeRadarChart();
            }
            else if (visual_type == 'flower') {
                chart = visual.makeFlowerChart();
            }
            else if (visual_type == 'radialBar') {
                chart = visual.makeRadialBarChart();
            }
            else if (visual_type == 'bar') {
                chart = visual.makeBarChart();
            }
            else if (visual_type == 'row') {
                chart = visual.makeRowChart();
            }
            else if (visual_type == 'bullet_bar') {
                chart = visual.makeBulletBarChart();
            }
            else if (visual_type == 'bullet_row') {
                chart = visual.makeBulletRow();
            }
            else if (visual_type == 'row_line') {
                chart = visual.makeRowLine();
            }
            else if (visual_type == 'bar_line') {
                chart = visual.makeBarLineChart();
            }
            else if (visual_type == 'line') {
                chart = visual.makeLineChart();
            }
            else if (visual_type == 'scatter') {
                chart = visual.makeScatterChart();
            }
            else if (visual_type == 'heatmap_geo') {
                chart = visual.makeHeatmapGeo();
            }
            else if (visual_type == 'scrcard_basic') {
    
                if ((self.el.id).indexOf('block') === -1) { // layout ketika di preview chart
                    self.$el.parents(".izi_dashboard_block_item").addClass("izi_dashboard_block_item_v_background");
                    self.$el.parent().addClass('izi_view_background');
                    self.$el.addClass('izi_view_scrcard_container');
                }else{ // layout ketika di block Dashboard 
                    self.$el.parents(".izi_dashboard_block_item").find(".izi_dashboard_block_title").text("");
                    self.$el.parents(".izi_dashboard_block_item").find(".izi_dashboard_block_header").addClass("izi_dashboard_block_btn_config");                    
                }
                visual.makeScorecardBasic();
            }
            else if (visual_type == 'scrcard_trend') {
    
                if ((self.el.id).indexOf('block') === -1) { // layout ketika di preview chart
                    self.$el.parents(".izi_dashboard_block_item").addClass("izi_dashboard_block_item_v_background");
                    self.$el.parent().addClass('izi_view_background');
                    self.$el.addClass('izi_view_scrcard_container');
                }else{ // layout ketika di block Dashboard 
                    self.$el.parents(".izi_dashboard_block_item").find(".izi_dashboard_block_title").text("");
                    self.$el.parents(".izi_dashboard_block_item").find(".izi_dashboard_block_header").addClass("izi_dashboard_block_btn_config");                    
                }
                visual.makeScorecardTrend();
            }
            else if (visual_type == 'scrcard_progress') {
    
                if ((self.el.id).indexOf('block') === -1) { // layout ketika di preview chart
                    self.$el.parents(".izi_dashboard_block_item").addClass("izi_dashboard_block_item_v_background");
                    self.$el.parent().addClass('izi_view_background');
                    self.$el.addClass('izi_view_scrcard_container');
                }else{ // layout ketika di block Dashboard 
                    self.$el.parents(".izi_dashboard_block_item").find(".izi_dashboard_block_title").text("");
                    self.$el.parents(".izi_dashboard_block_item").find(".izi_dashboard_block_header").addClass("izi_dashboard_block_btn_config");                    
                }
                visual.makeScorecardProgress();
            }
            // Get AI Analysis
            if (self.mode == 'ai_analysis')
                self._getLabAnalysisText(visual.data)
            // RTL
            if (chart && typeof chart === 'object' && self.rtl) {
                chart.rtl = true;
            }
            var style=''
            if(show_drill_button){
                style='style="display:block;"'
            }
            // Drill Up
            self.$el.find('.izi_reset_drilldown').remove();
            self.$el.append(`
            <button class="btn btn-sm btn-primary izi_reset_drilldown" `+ style +`>
            <i class="fa fa-chevron-up"></i>
            </button>
            `);
    
            // One step drill up
            self.$el.find('.izi_drillup').remove();
            self.$el.append(`
                <button class="btn btn-sm btn-primary izi_drillup" `+ style +`>
                    <i class="fa fa-arrow-left"></i>
                </button>
            `);
            // If Chart From Ask AI
            if (self.ask_chart && chart && chart.legend) {
                chart.legend.scrollable = false;
            }
        }
    },
    _makeOdooView: function (result) {
        var self = this
        const base_url = window.location.origin;
        var idElm = `visual_${self.analysis_id}`;
        if (self.block_id) {
            idElm = `block_${self.block_id}_${idElm}`;
        }
        self.$el.attr('id', idElm);
        self.$el.attr('data-analysis_id', self.analysis_id);
        self.$el.closest('.izi_dashboard_block_item').addClass('has_iframe');
        self.$el.closest('.izi_dashboard_block_item').find('.izi_dashboard_block_title').html('<span class="material-icons izi_btn_icon">settings</span>');
        // LAST OPTION IF USING IFRAME :
        self.$el.append(`
            <div class='w-100'>
                <iframe src="`+ base_url +`/web#action=`+ result['action_model_action_id'] +`&model=`+ result['action_model'] +`&view_type=`+ result['action_model_view_type'] +`&view_id=`+ result['action_model_view_id'] +`&iframe_fullscreen=true&menu_id=196" class="w-100 h-100"></iframe>
            </div>
            `)
    },
    _getLabAnalysisText: function (ai_analysis_data) {
        var self = this;
        if (self.analysis_id) {
            if (self.parent.$description) {
                self.parent.$description.append(`<span class="spinner-border spinner-border-small"/>`);
            }
            jsonrpc('/web/dataset/call_kw/izi.analysis/action_get_lab_description', {
                model: 'izi.analysis',
                method: 'action_get_lab_description',
                args: [self.analysis_id, ai_analysis_data, self.block_id],
                kwargs: {},
            }).then(function (result) {
                if (self.parent.$description) {
                    self.parent.$description.empty();
                }
                if (result.status == 200) {
                    if (self.parent.$description) {
                        self.parent.$description.html(result.ai_analysis_text);
                        self.parent.$speech_ai.show();
                    }
                } else if (self.index == 0) {
                    if (result.status == 401) {
                        new swal('Need Access', result.message, 'warning');
                        self._getOwl().action.doAction({
                            type: 'ir.actions.act_window',
                            name: _t('Need API Access'),
                            target: 'new',
                            res_model: 'izi.lab.api.key.wizard',
                            views: [[false, 'form']],
                            context: {},
                        },{
                            onClose: function(){
                            }
                        });
                    } else
                        new swal('Error', result.message, 'error');
                }
                self.mode = false;
                self.parent.mode = false;
            })
        }
    },
    _deleteVisual: function () {
        var self = this;
        self.$el.empty();
    },

    _setAnalysisVariables: function (result) {
        var self = this;
        // Set Variables
        self.max_drilldown_level = result.max_drilldown_level;
        self.action_id = result.action_id;
        self.action_external_id = result.action_external_id;
        self.action_model = result.action_model;
        self.analysis_name = result.analysis_name;
        self.field_by_alias = result.field_by_alias;
        self.model_field_names = result.model_field_names;
        self.field_type_by_alias = result.field_type_by_alias;
    },

    _getFilters: function () {
        var self = this;
        return self.filters;
    },

    _getDataAnalysis: function (kwargs, callback) {
        var self = this;
        if(kwargs && kwargs['filter_temp_values']){
            self.dynamicFilters = kwargs['filter_temp_values']
        }else{
            self.dynamicFilters = []
        }
        if (self.analysis_id) {
            if (self.context) {
                if (kwargs == undefined || kwargs == null || kwargs == false) {
                    kwargs = {};
                }
                kwargs.context = self.context;
            };
            let dashboard_id = $('#global_dashboard_id').val();
            if (dashboard_id) {
                kwargs.dashboard_id = parseInt(dashboard_id);
            }
            jsonrpc('/web/dataset/call_kw/izi.analysis/try_get_analysis_data_dashboard', {
                model: 'izi.analysis',
                method: 'try_get_analysis_data_dashboard',
                args: [self.analysis_id],
                kwargs: kwargs || {},
                context: self.context,
            }).then(function (result) {
                self._setAnalysisVariables(result);
                callback(result);
            })
        }
    },

    runDataScript: function (context={}, callback=undefined) {
        var self = this;
        if (self.analysis_id) {
            jsonrpc('/web/dataset/call_kw/izi.analysis/run_data_script', {
                model: 'izi.analysis',
                method: 'run_data_script',
                args: [self.analysis_id],
                kwargs: {
                    context: context,
                },
            }).then(function (result) {
                var args = {}
                if (self.filters) {
                    args.filters = self.filters;
                    args.mode = self.mode;
                }
                self._renderVisual(args);
                if (callback) {
                    callback(result);
                }
            })
        }
    },

    renderSumTableRow: function (result, table_data, tableIdElm) {
        var self = this;
        var prefix_by_field = result.prefix_by_field;
        var suffix_by_field = result.suffix_by_field;
        var decimal_places_by_field = result.decimal_places_by_field;
        var is_metric_by_field = result.is_metric_by_field;
        var locale_code_by_field = result.locale_code_by_field;
        var total_data = [];
        var total_tr_elm = ``;
        if (result && result.fields) {
            result.fields.forEach(function (field) {
                var index_field = result.fields.indexOf(field);
                if (field in is_metric_by_field) {
                    total_data[index_field] = 0
                    table_data.forEach(function (t_data) {
                        total_data[index_field] += parseFloat(t_data[index_field] || 0);
                    });
                    var prefix = '';
                    var suffix = '';
                    var decimal_places = 0;
                    var locale_code = 'en-US';
                    if (field in prefix_by_field) {
                        prefix = prefix_by_field[field] + ' ';
                    }
                    if (field in suffix_by_field) {
                        suffix = ' ' + suffix_by_field[field];
                    }
                    if (field in decimal_places_by_field) {
                        decimal_places = decimal_places_by_field[field];
                    }
                    if (field in locale_code_by_field) {
                        locale_code = locale_code_by_field[field];
                    }
                    total_data[index_field] = `${prefix}${parseFloat(total_data[index_field]||0).toLocaleString(locale_code, {minimumFractionDigits: decimal_places, maximumFractionDigits: decimal_places})}${suffix}`;
                    total_tr_elm += `<th class="gridjs-th"><span style="float:right;">${total_data[index_field]}</span></th>`;
                } else {
                    total_data[index_field] = '';
                    total_tr_elm += `<th class="gridjs-th"></th>`;
                }
            })
        }
        // Render
        if ($(`.${tableIdElm}`).length > 0 && total_data.length > 0 && total_tr_elm) {
            $(`.${tableIdElm} tfoot`).remove();
            $(`.${tableIdElm}`).append(`
                <tfoot>
                    ${total_tr_elm}
                </tfoot>
            `);
        }
    },

    formatTableColumns: function (result) {
        var self = this;
        var columns = [];
        var prefix_by_field = result.prefix_by_field;
        var suffix_by_field = result.suffix_by_field;
        var decimal_places_by_field = result.decimal_places_by_field;
        var is_metric_by_field = result.is_metric_by_field;
        var locale_code_by_field = result.locale_code_by_field;
        if (result && result.fields) {
            result.fields.forEach(function (field) {
                if (field in is_metric_by_field) {
                    var prefix = '';
                    var suffix = '';
                    var decimal_places = 0;
                    var locale_code = 'en-US';
                    if (field in prefix_by_field) {
                        prefix = prefix_by_field[field] + ' ';
                    }
                    if (field in suffix_by_field) {
                        suffix = ' ' + suffix_by_field[field];
                    }
                    if (field in decimal_places_by_field) {
                        decimal_places = decimal_places_by_field[field];
                    }
                    if (field in locale_code_by_field) {
                        locale_code = locale_code_by_field[field];
                    }
                    columns.push({
                        name: field,
                        formatter: (cell) => gridjs.html(`<span style="float:right;">${prefix}${parseFloat(cell||0).toLocaleString(locale_code, {minimumFractionDigits: decimal_places, maximumFractionDigits: decimal_places})}${suffix}</span>`)
                    });
                } else {
                    columns.push(field);
                }
            })
        }
        return columns;
    },

    _openAnalysisById: function (analysisId) {
        var self = this;
        if (analysisId) {
            self._getOwl().action.doAction({
                type: 'ir.actions.act_window',
                name: _t('Analysis'),
                target: 'new',
                res_id: analysisId,
                res_model: 'izi.analysis',
                views: [[false, 'izianalysis']],
                context: {
                    'analysis_id': analysisId,
                },
            },{
                onClose: function(){

                }
            });
        }
    },

    _openAnalysisByName: function (analysisName) {
        var self = this;
        if (analysisName) {
            jsonrpc('/web/dataset/call_kw/izi.analysis/search_read', {
                model: 'izi.analysis',
                method: 'search_read',
                args: [[['name', '=', analysisName]], ['id', 'name']],
                kwargs: {},
            }).then(function (results) {
                if (results) {
                    var result = results[0];
                    var analysisId = result.id;
                    self._getOwl().action.doAction({
                        type: 'ir.actions.act_window',
                        name: _t('Analysis'),
                        target: 'new',
                        res_id: analysisId,
                        res_model: 'izi.analysis',
                        views: [[false, 'izianalysis']],
                        context: {
                            'analysis_id': analysisId,
                        },
                    },{
                        onClose: function(){
        
                        }
                    });
                }
            });
        }
    },

    _onClickInput: function (ev) {
        var self = this;
    },

    _onClickButton: function (ev) {
        var self = this;
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

export default IZIViewVisual;