var selfDashboard = {}
selfDashboard.blocks = []
$(function() {
    var base_url = window.location.origin;
    selfDashboard.base_url = base_url
    var access_token = $('#access_token').val();
    var dashboard_id = $('#dashboard_id').val();
    selfDashboard.access_token = access_token
    selfDashboard.dashboard_id = dashboard_id
    $.ajax(`${base_url}/izi/dashboard/${dashboard_id}?access_token=${access_token}`, {
        headers: {
        },
        type : 'GET',
        success: async function(res, status){
            console.log("Response", res);
            if (res.data && res.code == 200) {
                // new swal('Success', 'Data Successfully Fetched', 'success');
                selfDashboard = res.data
                _loadThemes(selfDashboard.themes);
                generateDashboard(res.data);
                _initDashboardFilter();
            } else {
                if (res.data && res.data.error)
                    new swal("Error", `${res.data.error_descrip}`, "error");
                else
                    new swal("Error", "Internal Server Error", "error");
            }
        },
        error: function(xhr, textStatus, errorThrown){
            if (xhr.responseJSON && xhr.responseJSON.data)
                new swal("Error", xhr.responseJSON.data, "error");
            else
                new swal("Error", "Internal Server Error", "error");
        }
    });

    // Export Capture
    $('body').on('click', '#izi_export_capture', function(ev) {
        _onClickExportCapture(ev);
    });

    // Dropdown filter date
    $('body').on('click', '.izi_view', function (ev) {
        ev.stopPropagation();
        elmId = $(ev.currentTarget);

        $('.dropdown-menu').hide();
    });

    $('body').on('click', '.izi_view .dropdown-toggle', function (ev) {
        ev.stopPropagation();
        elmId = $(ev.currentTarget);

        if (($(elmId).parents().find('.izi_view').length) >= 1) {
            if ($(elmId).hasClass('show') || $(elmId).parent().find('.dropdown-menu').css('display') == 'none') {
                $(elmId).removeClass('.dropdown-menu');
                $('.dropdown-menu').hide();
                $(elmId).addClass('.dropdown-menu');
                $(elmId).removeClass('show');
                $(elmId).parent().find('.dropdown-menu').show();
            } else {
                $(elmId).removeClass('.dropdown-menu');
                $('.dropdown-menu').hide();
                $(elmId).addClass('.dropdown-menu');
                $(elmId).addClass('show');
                $(elmId).parent().find('.dropdown-menu').hide();
            }
        }
    });

    $('body').on('click', '.izi_view .o_datepicker', function(ev) {
        ev.stopPropagation();
        elmId = $(ev.currentTarget);

        if (($(elmId).parents().find('.izi_view').length) >= 1) {
            $('.bootstrap-datetime-picker').show();
        }
    });
    $('body').on('click', '.izi_view [data-toggle="collapse"]', function(ev) {
        ev.stopPropagation();
        elmId = $(ev.currentTarget).data('target');

        if (($(elmId).parents().find('.izi_view').length) >= 1) {
            if ($(elmId).hasClass('show')) {
                $(elmId).removeClass('show');
            } else {
                $(elmId).addClass('show');
            }
        };
    });

    // Select date filter
    $('body').on('click', '.izi_select_date_format', function(ev) {
        _onClickSelectDateFormat(ev);
    });

    // Select theme
    $('body').on('click', '.izi_select_theme', function(ev) {
        _onClickSelectTheme(ev);
    });
});

function _loadThemes(themes) {
    var self = {
        $themeContainer: $('.izi_select_theme_container')
    };
    self.$themeContainer.empty();
    themes.forEach(res => {
        self.$themeContainer.append(`<a theme-id="${res.id}" class="dropdown-item izi_select_theme izi_select_theme_${res.name}">${res.name}</a>`);
    });
}

function _onClickSelectTheme(ev) {
    var theme_id = parseInt($(ev.currentTarget).attr('theme-id'));
    var theme_name = $(ev.currentTarget).text();
    selfDashboard.themeTarget = $(ev.currentTarget);
    selfDashboard.theme_name = theme_name;
    if (theme_id && theme_name) {
        new swal({
            title: "Change confirmation",
            text: `
                Do you confirm to change the dashboard theme?
            `,
            icon: "warning",
            showCancelButton: true,
            confirmButtonText: 'Yes',
            heightAuto : false,
        }).then((result) => {
            if (result.isConfirmed) {
                new swal('Success', `Dashboard theme has been changed successfully`, 'success');
                $(".dropdown-item.izi_select_theme").removeClass("active");
                selfDashboard.themeTarget.addClass("active");
                generateDashboard(selfDashboard);
            }
        });
    }
}

function _initDashboardFilter() {
    selfDashboard.filterDateRange = {
            elm: $('#izi_dashboard_filter_date_range'),
            values: [null, null],
        };
    selfDashboard.filterDateFormat = {
            elm: $('#izi_dashboard_filter_date_format'),
            values: null,
        };
    selfDashboard.$dynamicFiltersContainer = $('#izi_dynamic_filter_container');
    selfDashboard.$dynamicFilters = {};
    selfDashboard.dashboard_id = $('#dashboard_id').val();
    selfDashboard.base_url = window.location.origin;

    var $dateFromElm = selfDashboard.filterDateRange.elm.find('#izi_date_from');
    var $dateToElm = selfDashboard.filterDateRange.elm.find('#izi_date_to');

    if (selfDashboard.filters.date_format) {
        selfDashboard.filterDateFormat.values = selfDashboard.filters.date_format;
        var dateFormatText =  selfDashboard.filterDateFormat.elm.find(`[data-date_format="${!(selfDashboard.filters.date_format) ? '' : selfDashboard.filters.date_format}"]`).text()
        selfDashboard.filterDateFormat.elm.find('.izi_dashboard_filter_content .dropdown-toggle').text(dateFormatText);
        if (selfDashboard.filters.date_format == 'custom') {
            selfDashboard.filterDateRange.values = selfDashboard.filters.date_range;
            $dateFromElm[0].value = selfDashboard.filters.date_range[0];
            $dateToElm[0].value = selfDashboard.filters.date_range[1];
            selfDashboard.filterDateRange.elm.show();
        }
        _loadFilteredDashboard();
    }

    // Date Range
    $dateFromElm.bootstrap_datepicker({
        language: "en",
        format: "yyyy-mm-dd",
        autoclose: true,
    });
    $dateToElm.bootstrap_datepicker({
        language: "en",
        format: "yyyy-mm-dd",
        autoclose: true,
    });
    $dateFromElm.off('change');
    $dateFromElm.on('change', function (ev) {
        var newValue = ev.currentTarget.value ? moment(ev.currentTarget.value).format('YYYY-MM-DD') : null;
        if (selfDashboard.filterDateRange.values[0] != newValue) {
            selfDashboard.filterDateRange.values[0] = newValue;
            selfDashboard.filterDateFormat.values = 'custom';
            selfDashboard.filters.date_range[0] = newValue;
            selfDashboard.filters.date_format = 'custom';
            _loadFilteredDashboard();
        }
    });
    $dateToElm.off('change');
    $dateToElm.on('change', function (ev) {
        var newValue = ev.currentTarget.value ? moment(ev.currentTarget.value).format('YYYY-MM-DD') : null;
        if (selfDashboard.filterDateRange.values[1] != newValue) {
            selfDashboard.filterDateRange.values[1] = newValue;
            selfDashboard.filterDateFormat.values = 'custom';
            selfDashboard.filters.date_range[1] = newValue;
            selfDashboard.filters.date_format = 'custom';
            _loadFilteredDashboard();
        }
    });

    // Initiate Dynamic Filter
    selfDashboard.$dynamicFiltersContainer.empty();
    $.ajax(`${selfDashboard.base_url}/izi/dashboard/filters/${selfDashboard.dashboard_id}`, {
        headers: {
        },
        type : 'GET',
        success: async function(res, status){
            if (res.data && res.code == 200) {
                const results = res.data;
                results.forEach(function (filter) {
                    if (results[0] == filter) {
                        selfDashboard.$dynamicFiltersContainer.append(`
                            <div class="izi_dashboard_filter">
                                <div class="izi_dashboard_filter_title dropdown izi_dropdown">
                                    <span class="material-icons-outlined">filter_alt</span>
                                </div>
                                <div class="izi_dashboard_filter_content">
                                    <input type="hidden" class="izi_wfull izi_select2" id="filter_${filter.id}"/>
                                </div>
                            </div>`);
                    } else {
                        selfDashboard.$dynamicFiltersContainer.append(`
                            <div class="izi_dashboard_filter">
                                <input type="hidden" class="izi_wfull izi_select2" id="filter_${filter.id}"/>
                            </div>`);
                    }
                    if (filter.params) {
                        var $dF = new IZIAutocomplete(selfDashboard, {
                            elm: selfDashboard.$dynamicFiltersContainer.find(`#filter_${filter.id}`),
                            multiple: filter.selection_type == 'multiple' ? true : false,
                            placeholder: filter.name,
                            minimumInput: false,
                            params: filter.params,
                            onChange: function (values, name) {
                                selfDashboard.$dynamicFilters[filter.id].values = values;
                                _loadFilteredDashboard();
                            },
                        });
                    } else {
                        var $dF = new IZIAutocomplete(selfDashboard, {
                            elm: selfDashboard.$dynamicFiltersContainer.find(`#filter_${filter.id}`),
                            multiple: filter.selection_type == 'multiple' ? true : false,
                            placeholder: filter.name,
                            minimumInput: false,
                            data: filter.values,
                            params: {
                                textField: 'name',
                            },
                            onChange: function (values, name) {
                                selfDashboard.$dynamicFilters[filter.id].values = values;
                                _loadFilteredDashboard();
                            },
                        });
                    }
                    selfDashboard.$dynamicFilters[filter.id] = {
                        values: [],
                        elm: $dF,
                    };
                });
            }
        },
        error: function(xhr, textStatus, errorThrown){
            if (xhr.responseJSON && xhr.responseJSON.data)
                new swal("Error", xhr.responseJSON.data, "error");
            else
                new swal("Error", "Internal Server Error", "error");
        }
    });
}

function _onClickSelectDateFormat(ev) {
    selfDashboard.filterDateRange = {
        elm: $('#izi_dashboard_filter_date_range'),
        values: [null, null],
    };
    selfDashboard.filterDateFormat = {
        elm: $('#izi_dashboard_filter_date_format'),
        values: null,
    };

    selfDashboard.filterDateFormat.values = $(ev.currentTarget).data('date_format');
    selfDashboard.filters.date_format = $(ev.currentTarget).data('date_format');
    var text = $(ev.currentTarget).text();
    selfDashboard.filterDateFormat.elm.find('.izi_dashboard_filter_content .dropdown-toggle').text(text);
    if (selfDashboard.filterDateFormat.values == 'custom') {
        selfDashboard.filterDateRange.elm.show();
    } else {
        selfDashboard.filterDateRange.elm.hide();
        _loadFilteredDashboard();
    }
}

function _loadFilteredDashboard(mode=false) {
    var date_format = selfDashboard.filters.date_format;
    var date_range = selfDashboard.filters.date_range;
    if (date_format) {
        _updateSubtitleText(date_format)
        if (date_format == 'custom' && date_range.every(element => element !== null)) {
            var start_date = date_range[0];
            var end_date = date_range[1];
            subtitle = start_date + " to " + end_date;
            $('.izi_config_dashboard').find('.izi_subtitle').text(subtitle);
        }
    } else {
        ['date_format', 'date_range'].forEach(prop => delete selfDashboard.filters[prop]);
        $('.izi_config_dashboard').find('.izi_subtitle').text('');
    }

    if (selfDashboard.$dynamicFilters) {
        selfDashboard.filters.dynamic = [];
        for (var key in selfDashboard.$dynamicFilters) {
            selfDashboard.filters.dynamic.push({
                filter_id: parseInt(key),
                values: selfDashboard.$dynamicFilters[key].values,
            });
        }
    }
    generateDashboard(selfDashboard);
}

function _updateSubtitleText(date_format){
    var self = {
        $configDashboard: $('.izi_config_dashboard')
    };
    var subtitle = "";

    if (date_format == "today") {
        subtitle = moment().format('DD-MMM-YYYY');
    
    } else if (date_format == "this_week") {
        var start_date = moment().startOf('week').format('DD-MMM-YYYY');
        var end_date = moment().endOf('week').format('DD-MMM-YYYY');
        subtitle = start_date + " to " + end_date;
    
    } else if (date_format == "this_month") {
        var start_date = moment().startOf('month').format('DD-MMM-YYYY');
        var end_date = moment().endOf('month').format('DD-MMM-YYYY');
        subtitle = start_date + " to " + end_date;
    
    } else if (date_format == "this_year") {
        var start_date = moment().startOf('year').format('DD-MMM-YYYY');
        var end_date = moment().endOf('year').format('DD-MMM-YYYY');
        subtitle = start_date + " to " + end_date;
    
    } else if (date_format == "mtd") {
        var start_date = moment().startOf('month').format('DD-MMM-YYYY');
        var end_date = moment().format('DD-MMM-YYYY');
        subtitle = start_date + " to " + end_date;
    
    } else if (date_format == "ytd") {
        var start_date = moment().startOf('year').format('DD-MMM-YYYY');
        var end_date = moment().format('DD-MMM-YYYY');
        subtitle = start_date + " to " + end_date;
    
    } else if (date_format == "last_week") {
        var start_date = moment().subtract(1, 'week').startOf('week').format('DD-MMM-YYYY');
        var end_date = moment().subtract(1, 'week').endOf('week').format('DD-MMM-YYYY');
        subtitle = start_date + " to " + end_date;
    
    } else if (date_format == "last_month") {
        var start_date = moment().subtract(1, 'month').startOf('month').format('DD-MMM-YYYY');
        var end_date = moment().subtract(1, 'month').endOf('month').format('DD-MMM-YYYY');
        subtitle = start_date + " to " + end_date;
    
    } else if (date_format == "last_two_months") {
        var start_date = moment().subtract(2, 'months').startOf('month').format('DD-MMM-YYYY');
        var end_date = moment().subtract(1, 'month').endOf('month').format('DD-MMM-YYYY');
        subtitle = start_date + " to " + end_date;
    
    } else if (date_format == "last_three_months") {
        var start_date = moment().subtract(3, 'months').startOf('month').format('DD-MMM-YYYY');
        var end_date = moment().subtract(1, 'month').endOf('month').format('DD-MMM-YYYY');
        subtitle = start_date + " to " + end_date;
    
    } else if (date_format == "last_year") {
        var start_date = moment().subtract(1, 'year').startOf('year').format('DD-MMM-YYYY');
        var end_date = moment().subtract(1, 'year').endOf('year').format('DD-MMM-YYYY');
        subtitle = start_date + " to " + end_date;
    
    } else if (date_format == "last_10") {
        var start_date = moment().subtract(10, 'days').format('DD-MMM-YYYY');
        var end_date = moment().format('DD-MMM-YYYY');
        subtitle = start_date + " to " + end_date;
    
    } else if (date_format == "last_30") {
        var start_date = moment().subtract(30, 'days').format('DD-MMM-YYYY');
        var end_date = moment().format('DD-MMM-YYYY');
        subtitle = start_date + " to " + end_date;
    
    } else if (date_format == "last_60") {
        var start_date = moment().subtract(60, 'days').format('DD-MMM-YYYY');
        var end_date = moment().format('DD-MMM-YYYY');
        subtitle = start_date + " to " + end_date;
    }
    
    self.$configDashboard.find('.izi_subtitle').text(subtitle);
}

function generateDashboard(data) {
    var self = {};
    var dashboardBlocks = data.blocks;
    var themeName = data.theme_name;
    amChartsTheme.applyTheme(themeName);
    self.dashboardBlocks = dashboardBlocks;
    self.$blocks = [];
    // Init Grid
    if (!self.$grid) {
        self.$grid = GridStack.init();
        self.$grid.margin(7);
        self.$grid.float('true');
        self.$grid.cellHeight(125);
    }
    self.$grid.enableMove(false);
    self.$grid.enableResize(false);
    self.$grid.removeAll();
    // For Each Dashboard Block
    var nextY = 0;
    var index = 0;
    self.dashboardBlocks.forEach(block => {
        var isScoreCard = false;
        if (block.visual_type_name && block.visual_type_name.toLowerCase().indexOf("scrcard") >= 0)
            isScoreCard = true;
        if (self.mode == 'ai_analysis') {
            if (isScoreCard) {
                block.gs_x = 0;
                block.gs_h = 2;
                block.gs_w = 12;
            } else {
                block.gs_x = 0;
                block.gs_h = 4;
                block.gs_w = 12;
            }
        }
        var widgetValues = {
            'id': block.id,
            'w': block.gs_w,
            'h': block.gs_h,
            'x': block.gs_x,
            'y': block.gs_y,
            'minW': block.min_gs_w,
            'minH': block.min_gs_h,
            // 'autoPosition': 'true',
        }
        if (window.innerWidth <= 792 || self.mode == 'ai_analysis') {
            widgetValues.y = nextY;
            nextY += widgetValues.h;
        }
        self.$grid.addWidget(widgetValues);
        // Init IZIViewDashboardBlock
        if (block.analysis_id) {
            var args = {
                'id': block.id,
                'analysis_id': block.analysis_id[0],
                'analysis_name': block.analysis_id[1],
                'animation': block.animation,
                'filters': self.filters,
                'refresh_interval': block.refresh_interval,
                'index': index,
                'mode': self.mode,
                'visual_type_name': block.visual_type_name,
                'rtl': block.rtl,
            }

            if (block.animation) {
                am4core.useTheme(am4themes_animated);
            } else {
                am4core.unuseTheme(am4themes_animated);
            }

            index += 1;
            var $block = $(`
                <div class="izi_dashboard_block_item" data-id="${block.id}">
                    <div class="izi_dashboard_block_header">
                        <div class="izi_block_left izi_dropdown dropdown">
                            <h4 class="izi_dashboard_block_title dropdown-toggle" data-toggle="dropdown">${block.analysis_id[1]}</h4>
                            <div class="dropdown-menu">
                                <a class="dropdown-item izi_action_quick_open_analysis">Open Analysis</a>
                                <a class="dropdown-item izi_action_edit_analysis">Configuration</a>
                                <a class="dropdown-item izi_action_open_list_view">View List</a>
                                <a class="dropdown-item izi_action_export_excel" data-id="${block.id}">Export Excel</a>
                                <a class="dropdown-item izi_action_delete_block" data-id="${block.id}">Remove Analysis</a>
                            </div>
                        </div>
                    </div>
                    <div class="izi_dashboard_block_content">
                        <div class="izi_view_visual h-100"></div>
                    </div>
                </div>
            `);
            $block.appendTo($(`.grid-stack-item[gs-id="${block.id}"] .grid-stack-item-content`));
            generateVisual(block);
            self.$blocks.push($block);
            block.drilldown_level = 0
            block.drilldown_history = []
            // selfDashboard['$blocks'].push(block)
        }
    });
}
function combineKwargs(kwargs,args){
    var kwargs_obj = JSON.parse(kwargs)
    var new_kwargs = {
        ...kwargs_obj,
        ...args,
        filters: {
            ...kwargs_obj.filters,
            ...args.filters
        }
    }
    new_kwargs = JSON.stringify(new_kwargs)
    return new_kwargs
}
function generateVisual(block, args = false) {
    var base_url = window.location.origin;
    var access_token = $('#access_token').val();
    var kwargs = JSON.stringify({
        filters: selfDashboard.filters || {}
    });
    if(args){
        kwargs = combineKwargs(kwargs,args)
    }
    $.ajax(`${base_url}/izi/analysis/${block.analysis_id[0]}/data?access_token=${access_token}&kwargs=${kwargs}`, {
        headers: {
        },
        type : 'GET',
        success: async function(res, status){
            if (res.data && res.code == 200) {
                makeChart(block, res.data);
            } else {
                if (res.data && res.data.error)
                    new swal("Error", `${res.data.error_descrip}`, "error");
                else
                    new swal("Error", "Internal Server Error", "error");
            }
        },
        error: function(xhr, textStatus, errorThrown){
            if (xhr.responseJSON && xhr.responseJSON.data)
                new swal("Error", xhr.responseJSON.data, "error");
            else
                new swal("Error", "Internal Server Error", "error");
        }
    });
}
function _findElementBlock(analysis_id){
    var selected_block = false
    selfDashboard.blocks.forEach(block => {
        if(parseInt(analysis_id) == block['analysis_id'][0]){
            selected_block = block
        }
    });
    return selected_block
}

function _onHitChart(ev, visual, val) {
    var base_url = window.location.origin;
    var analysis_id = false;
    var clicked_visual = ev.event.target;
    var block_element = clicked_visual.closest('.izi_dashboard_block_item');

    if (block_element) {
        block_id = block_element.getAttribute('data-id');
        var visual_element = block_element.querySelector('.izi_view_visual');

        if (visual_element) {
            // Get the id of the child element
            var visual_id = visual_element.id; // e.g., "block_4_visual_3"
            
            var prefix = `block_${block_id}_visual_`;
            var analysis_id = parseInt(visual_id.replace(prefix, ''));
        }
    }
    visual = _findElementBlock(analysis_id)
    var self = visual
    if (self && self.dimension_alias && val) {
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
        $.ajax(`${base_url}/izi/analysis/${self.analysis_id[0]}/ui_get_available_fields`, {
            headers: {
            },
            type : 'GET',
            success: async function(res, status){
                var res = res.data[1]
                res.forEach(item => {
                    const menu_item = document.createElement('div');
                    menu_item.className = 'drilldown-fields-item';
                    menu_item.textContent = item.name;
                    menu_item.setAttribute('field-id', item.id);
                    menu_item.addEventListener('click', () => {
                        if (self.drilldown_level == 0){
                            if (!self.filters){
                                // self.filters = {};

                                self.filters = selfDashboard.filters
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
                                additional_action_filters = _formatDomains(field_name, '=', val[self.dimension_alias]);
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
                        _getDataAnalysis(self, args, function (result) {
                            self.temp_analysis_data = result.data;
                            makeChart(self, result);
                            self.$el.find('.izi_reset_drilldown').show();
                            self.$el.find('.izi_drillup').show();
                        });
                        drilldown_background.remove();
                    });
                    drilldown_fields_menus.appendChild(menu_item);
                })
            },
            error: function(xhr, textStatus, errorThrown){
                if (xhr.responseJSON && xhr.responseJSON.data)
                    new swal("Error", xhr.responseJSON.data, "error");
                else
                    new swal("Error", "Internal Server Error", "error");
            }
        })
        document.body.appendChild(drilldown_background);

        const rect = drilldown_fields.getBoundingClientRect();
        const viewportHeight = window.innerHeight - 500;
        if (rect.bottom > viewportHeight) {
            const newTopPosition = top_position - (rect.bottom - viewportHeight) - 10;
            drilldown_fields.style.top = `${newTopPosition}px`;
        }
    }
}
function _formatDomains(field_name, operator, value) {
    // store original locale
    var originalLocale = moment.locale();

    // set locale to english
    moment.locale('en');

    var start_date = null;
    var end_date = null;

    if (moment(value, 'DD MMM YYYY', true).isValid()) {
        start_date = moment(value, 'DD MMM YYYY', true).format('YYYY-MM-DD');
        end_date = moment(value, 'DD MMM YYYY', true).add(1, 'd').format('YYYY-MM-DD');
    } else if (moment(value, 'DD MMMM YYYY', true).isValid()) {
        start_date = moment(value, 'DD MMMM YYYY', true).format('YYYY-MM-DD');
        end_date = moment(value, 'DD MMMM YYYY', true).add(1, 'M').format('YYYY-MM-DD');
    } else if (moment(value, 'MMM YYYY', true).isValid()) {
        start_date = moment(value, 'MMM YYYY', true).format('YYYY-MM-DD');
        end_date = moment(value, 'MMM YYYY', true).add(1, 'M').format('YYYY-MM-DD');
    } else if (moment(value, 'MMMM YYYY', true).isValid()) {
        start_date = moment(value, 'MMMM YYYY', true).format('YYYY-MM-DD');
        end_date = moment(value, 'MMMM YYYY', true).add(1, 'M').format('YYYY-MM-DD');
    } else if (moment(value, 'YYYY', true).isValid()) {
        start_date = moment(value, 'YYYY', true).format('YYYY-MM-DD');
        end_date = moment(value, 'YYYY', true).add(1, 'Y').format('YYYY-MM-DD');
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
}
function _getDataAnalysis(self, kwargs, callback) {
    var base_url = window.location.origin;
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
            kwargs.context = self.context || "";
        };
        const string_kwargs = encodeURIComponent(JSON.stringify(kwargs));
        var this_access_token = $('#access_token').val();
        $.ajax(`${base_url}/izi/analysis/${self.analysis_id[0]}/try_get_analysis_data_dashboard?kwargs=${string_kwargs}&access_token=${this_access_token}`, {
            headers: {
            },
            type : 'GET',
            success: async function(res, status){
                var result = res.data
                callback(result);
            },
            error: function(xhr, textStatus, errorThrown){
                if (xhr.responseJSON && xhr.responseJSON.data)
                    new swal("Error", xhr.responseJSON.data, "error");
                else
                    new swal("Error", "Internal Server Error", "error");
            }
        })
    }
}
function makeChart(block, result) {
    var self = {
        $el: $(`.izi_dashboard_block_item[data-id="${block.id}"] .izi_view_visual`),
        analysis_id: block.analysis_id[0],
        block_id: block.id,
        animation: block.animation,
        filters: block.filters,
        refresh_interval: block.refresh_interval,
        index: block.index,
        mode: block.mode,
        visual_type_name: block.visual_type_name,
        rtl: block.rtl,
        formatTableColumns: function(res){
            var columns = [];
            var prefix_by_field = res.prefix_by_field;
            var suffix_by_field = res.suffix_by_field;
            var decimal_places_by_field = res.decimal_places_by_field;
            var is_metric_by_field = res.is_metric_by_field;
            var locale_code_by_field = res.locale_code_by_field;
            if (res && res.fields) {
                res.fields.forEach(function (field) {
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
    };

    // TODO: Make it more elegant
    self.$el.parent().removeClass('izi_view_background');
    self.$el.removeClass('izi_view_scrcard_container scorecard scorecard-sm');
    self.$el.parents(".izi_dashboard_block_item").removeClass("izi_dashboard_block_item_v_background");

    var visual_type = result.visual_type;
    var data = result.data;
    var table_data = result.values;
    var columns = result.fields;

    var idElm = `visual_${self.analysis_id}`;
    if (self.block_id) {
        idElm = `block_${self.block_id}_${idElm}`;
    }
    block['dimension_alias'] = result.dimensions[0]
    block['field_type_by_alias'] = result.field_type_by_alias
    block['field_by_alias'] = result.field_by_alias
    block['$el'] = self.$el
     
    self.$el.attr('id', idElm);
    if ($(`#${idElm}`).length == 0) return false;
    var chart;
    var visual = new amChartsComponent({
        title: result.analysis_name,
        idElm: idElm,
        data: data,
        dimension: result.dimensions[0], // TODO: Only one dimension?
        metric: result.metrics,
        callback: _onHitChart,
            
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
        rotateLabel: result.visual_config_values.rotateLabel,
        scrollbar: result.visual_config_values.scrollbar,
        currency_code: result.visual_config_values.currency_code,
        particle: result.visual_config_values.particle,
        trends: result.visual_config_values.trends,
        trendLine: result.visual_config_values.trendLine,
        mapView: result.visual_config_values.mapView
    });
    if (visual_type == 'custom') {
        if (result.use_render_visual_script && result.render_visual_script) {
            // console.log('Render Visual Script', result.use_render_visual_script, result.render_visual_script);
            try {
                eval(result.render_visual_script);
            } catch (error) {
                new swal('Render Visual Script: JS Error', error.message, 'error')
            }
        }
    }
    else if (visual_type == 'iframe') {
        if (result.visual_config_values.iframeHTMLTag || result.visual_config_values.iframeURL) {
            console.log('Render Iframe', result.visual_config_values.iframeHTMLTag, result.visual_config_values.iframeURL);
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
        if (!self.grid) {
            self.grid = new gridjs.Grid({
                columns: columns,
                data: tableToLocaleString(table_data),
                sort: true,
                pagination: true,
                resizable: true,
                // search: true,
            }).render($(`#${idElm}`).get(0));
        } else {
            self.grid.updateConfig({
                columns: columns,
                data: table_data,
            }).forceRender();
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

        if ((self.$el.attr('id')).indexOf('block') === -1) { // layout ketika di preview chart
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

        if ((self.$el.attr('id')).indexOf('block') === -1) { // layout ketika di preview chart
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

        if ((self.$el.attr('id')).indexOf('block') === -1) { // layout ketika di preview chart
            self.$el.parents(".izi_dashboard_block_item").addClass("izi_dashboard_block_item_v_background");
            self.$el.parent().addClass('izi_view_background');
            self.$el.addClass('izi_view_scrcard_container');
        }else{ // layout ketika di block Dashboard 
            self.$el.parents(".izi_dashboard_block_item").find(".izi_dashboard_block_title").text("");
            self.$el.parents(".izi_dashboard_block_item").find(".izi_dashboard_block_header").addClass("izi_dashboard_block_btn_config");                    
        }
        visual.makeScorecardProgress();
    }
    
    // RTL
    if (chart && self.rtl) {
        chart.rtl = true;
    }

    var style='style="display:none;"'
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

    self.$el.find('.izi_reset_drilldown').on('click', function(event) {
        var visual = false
        var analysis_id = false;
        var clicked_visual = event.target;
        var block_element = clicked_visual.closest('.izi_dashboard_block_item');
        if (block_element) {
            block_id = block_element.getAttribute('data-id');
            var visual_element = block_element.querySelector('.izi_view_visual');

            if (visual_element) {
                // Get the id of the child element
                var visual_id = visual_element.id; // e.g., "block_4_visual_3"
                
                var prefix = `block_${block_id}_visual_`;
                var analysis_id = parseInt(visual_id.replace(prefix, ''));
            }
        }
        visual = _findElementBlock(analysis_id)
        resetDrilldown(visual)
    });

    self.$el.find('.izi_drillup').on('click', function(event) {
        var visual = false
        var analysis_id = false;
        var clicked_visual = event.target;
        var block_element = clicked_visual.closest('.izi_dashboard_block_item');
        if (block_element) {
            block_id = block_element.getAttribute('data-id');
            var visual_element = block_element.querySelector('.izi_view_visual');

            if (visual_element) {
                // Get the id of the child element
                var visual_id = visual_element.id; // e.g., "block_4_visual_3"
                
                var prefix = `block_${block_id}_visual_`;
                var analysis_id = parseInt(visual_id.replace(prefix, ''));
            }
        }
        visual = _findElementBlock(analysis_id)
        visual.drilldown_level = visual.drilldown_level - 1;
        var history = visual.drilldown_history
        var key = history.length - 2
        var args = {}
        if(visual.drilldown_history.length > 1){
            if (visual.filters)
                visual.filters = history[key].drilldown_filters
            args = {
                'mode': history[key].drilldown_mode,
                'filters': history[key].drilldown_filters,
                'drilldown_level': history[key].drilldown_level,
                'drilldown_field': history[key].drilldown_field,
                'drilldown_field_subtype': history[key].drilldown_field_subtype
            };
            // self.filters = history[key].drilldown_filters
            if (visual.dynamicFilters){
                args['filter_temp_values'] = visual.dynamicFilters
            }
            history.pop()
            _getDataAnalysis(visual, args, function (result) {
                self.temp_analysis_data = result.data;
                makeChart(visual, result)
                visual.$el.find('.izi_reset_drilldown').show();
                visual.$el.find('.izi_drillup').show();
            })
        }else{
            resetDrilldown(visual)
        }
    });
}
function resetDrilldown(visual) {
     
    visual.drilldown_history = []
    visual.drilldown_level = 0;
    if (visual.filters)
        visual.filters.action = [];
    var args = {}
    if (visual.filters) {
        args.filters = visual.filters;
        args.mode = visual.mode;
    }
    if (visual.dynamicFilters){
        args['filter_temp_values'] = visual.dynamicFilters
    }
    _getDataAnalysis(visual, args, function (result) {
        visual.temp_analysis_data = result.data;
        makeChart(visual, result)
        visual.$el.find('.izi_reset_drilldown').hide();
        visual.$el.find('.izi_drillup').hide();
    })
}

function tableToLocaleString(table_data) {
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
}

function _onClickExportCapture(ev) {
    var self = {
        $titleDashboard: $('.izi_title_dashboard'),
        $btnExportCapture: $('#izi_export_capture'),
        $btnExportLoading: $('#izi_export_capture_loading'),
        selectedDashboard: $('#dashboard_id').val()
    }

    self.$btnExportCapture.hide();
    self.$btnExportLoading.show();

    ev.stopPropagation();
    if (self.selectedDashboard) {
        // self.$captureContainer.on('click', function(){
        // var btn = $(self).button('loading');
        html2canvas(document.querySelector('.izi_view'), {useCORS: true, allowTaint: false}).then(function(canvas){
            window.jsPDF = window.jspdf.jsPDF;
            var doc = new jsPDF("p", "mm", "a4");
            var img = canvas.toDataURL("image/jpeg", 0.90);
            var imgProps= doc.getImageProperties(img);
            var pageHeight = 295;
            var width = doc.internal.pageSize.getWidth();
            var height = (imgProps.height * width) / imgProps.width;
            var heightLeft = height;
            var position = 0;
            
            doc.addImage(img,'JPEG', 0, 0, width, height, 'FAST');
            heightLeft -= pageHeight;
            while (heightLeft >= 0) {
                position = heightLeft - height;
                doc.addPage();
                doc.addImage(img, 'JPEG', 0, position,  width, height, 'FAST');
                heightLeft -= pageHeight;
            };
            doc.save(self.$titleDashboard[0].innerText + '.pdf');
            new swal('Success', `Dashboard has been Captured.`, 'success');
            // btn.button('reset');

            self.$btnExportCapture.show();
            self.$btnExportLoading.hide();
        });
    } 
}

// Constructor
class IZIAutocomplete {
    constructor(parent, args) {
        var self = this;
        self.base_url = window.location.origin;
        self.parent = parent;
        self.elm = args.elm;
        self.multiple = args.multiple;
        self.placeholder = args.placeholder;
        self.params = args.params;
        self.analysisId = args.analysisId;
        self.isDynamic = args.isDynamic;
        self.fixPosition = args.fixPosition || false;
        self.noAllOption = args.noAllOption || false;
        self.initData = args.initData || (args.multiple ? null : {});
        if (args.formatFunc) {
            self.formatFunc = args.formatFunc;
        } else {
            self.formatFunc = function format(item) { 
                return item[self.params.textField || 'name']; 
            }
        }
        self.onChange = args.onChange;
        self.selectedId;
        self.selectedText = '';
        self.selectedValue = '';
        self.selectedLabel = '';
        if (args.minimumInput)
            self.minimumInputLength = 1;
        else
            self.minimumInputLength = 0;
        self.data = args.data;
        self.api = args.api;
        self.tags = args.tags || false;
        self.createSearchChoice = args.createSearchChoice || false;
        if (self.data) {
            self.initWithData();
        } else if (self.api) {
            self.initWithAPI();
        } else if (self.isDynamic) {
            self.initWithORMDynamic();
        }else{
            self.initWithORM();
        }
        self.initOnChange();
    }
    set(key, value) {
        var self = this;
        self[key] = value;
    }
    setDomain(domain) {
        var self = this;
        self.params.domain = domain;
        self.initWithORM();
    }
    destroy() {
        var self = this;
        self.elm.select2('destroy');
    }
    initWithData(){
        var self = this;
        var typingTimer;
        var loadingRPC = false;
        var data = self.data;
        if (!self.multiple || !self.isDynamic) {
            var clearOption = {
                'id': null,
                'value': null,
                'name': 'All',
            }
            data = [clearOption].concat(data);
        }
        self.elm.select2({
            multiple: self.multiple,
            allowClear: true, 
            tokenSeparators: [','], 
            minimumResultsForSearch: 10, 
            placeholder: self.placeholder,
            minimumInputLength: self.minimumInputLength,
            data: { results: data, text: self.params.textField || 'name' },
            formatSelection: self.formatFunc,
            formatResult: self.formatFunc,
            initSelection : function (element, callback) {
                callback(self.initData);
            }
        })
    }
    initWithORMDynamic(){
        var self = this;
        var typingTimer;
        var loadingRPC = false;

        self.elm.select2({
            multiple: self.multiple,
            allowClear: true, 
            tokenSeparators: [','], 
            minimumResultsForSearch: 10, 
            placeholder: self.placeholder,
            minimumInputLength: self.minimumInputLength,
            query: function (query) {
                var data = {results: []};
                loadingRPC = true;
                var kwargs = JSON.stringify({
                    params: self.params || {},
                    query_term: query.term || ''
                });
                $.ajax(`${self.base_url}/izi/analysis/fields/dynamic/${self.analysisId}?kwargs=${kwargs}`, {
                    headers: {
                    },
                    type : 'GET',
                    success: async function(res, status){
                        if (res.data && res.code == 200) {
                            const results = res.data;
                            var data = [];
                            var values = [];
                            if (results){
                                results.forEach(function (result) {
                                    var dt = {
                                        'name':result.name,
                                        'value':result.field_name,
                                        'id':result.id,
                                    }
                                    if (!values.includes(dt.value) && dt.value) {
                                        values.push(dt.value);
                                        data.push(dt);
                                    }
                                });
                            }
                            query.callback({results: data});
                            loadingRPC = false;
                            setTimeout(function() {
                                var drop_element = $("#select2-drop")
                                var left_position = self.parent.$el.find("#izi_dynamic_filter_container_custom").position().left;
                                var new_left = left_position - 120;
                                drop_element.css('left', new_left + 'px');
                                drop_element.css('width','200px');
                            }, 0); 
                        }
                    },
                    error: function(xhr, textStatus, errorThrown){
                        if (xhr.responseJSON && xhr.responseJSON.data)
                            new swal("Error", xhr.responseJSON.data, "error");
                        else
                            new swal("Error", "Internal Server Error", "error");
                    }
                });
            },
            formatSelection: self.formatFunc,
            formatResult: self.formatFunc,
            initSelection : function (element, callback) {
                callback(self.initData);
            }
        })
    }
    initWithORM(){
        var self = this;
        var typingTimer;
        var loadingRPC = false;
        self.elm.select2({
            multiple: self.multiple,
            allowClear: true, 
            tokenSeparators: [','], 
            minimumResultsForSearch: 10, 
            placeholder: self.placeholder,
            minimumInputLength: self.minimumInputLength,
            query: function (query) {
                var data = {results: []};
                var domain = [[self.params.textField, 'ilike', query.term]];
                if (Array.isArray(self.params.domain)  && self.params.domain.length)
                    Array.prototype.push.apply(domain, self.params.domain)
                clearTimeout(typingTimer);
                if (query && !loadingRPC && self.params) {
                    typingTimer = setTimeout(function() {
                        //do something
                        loadingRPC = true;
                        var kwargs = JSON.stringify({
                            params: self.params || {},
                            query_term: query.term || ''
                        });
                        $.ajax(`${self.base_url}/izi/dashboard/filters/values?kwargs=${kwargs}`, {
                            headers: {
                            },
                            type : 'GET',
                            success: async function(res, status){
                                // console.log("Response", res);
                                if (res.data && res.code == 200) {
                                    const results = res.data;
                                    var data = [];
                                    var values = [];
                                    results.forEach(function (result) {
                                        var dt = {
                                            'name': result[self.params.textField || 'name'],
                                            'value': self.params.modelFieldValues == 'field' ? result[self.params.textField] : result['id'],
                                            'id': self.params.modelFieldValues == 'field' ? result[self.params.textField] : result['id'],
                                        }
                                        if (self.params.textField) {
                                            dt[self.params.textField] = result[self.params.textField];
                                        }
                                        if (!values.includes(dt.value) && dt.value) {
                                            values.push(dt.value);
                                            data.push(dt);
                                        }
                                    });
                                    if (!self.multiple && !self.noAllOption) {
                                        var clearOption = {
                                            'id': null,
                                            'value': null,
                                            'name': 'All',
                                        }
                                        if (self.params.textField) {
                                            clearOption[self.params.textField] = 'All';
                                        }
                                        data = [clearOption].concat(data);
                                    }
                                    query.callback({results: data});
                                    loadingRPC = false;
                                    if (self.fixPosition){
                                        setTimeout(function() {
                                            var drop_element = $("#select2-drop")
                                            var left_position = self.parent.$el.find("#izi_dynamic_filter_container_custom").position().left;
                                            var new_left = left_position - 120;
                                            drop_element.css('left', new_left + 'px');
                                            drop_element.css('width','200px');
                                        }, 0);
                                    }
                                }
                            },
                            error: function(xhr, textStatus, errorThrown){
                                if (xhr.responseJSON && xhr.responseJSON.data)
                                    new swal("Error", xhr.responseJSON.data, "error");
                                else
                                    new swal("Error", "Internal Server Error", "error");
                            }
                        });
                    }, 500);
                }
                
            },
            formatSelection: self.formatFunc,
            formatResult: self.formatFunc,
            initSelection : function (element, callback) {
                callback(self.initData);
            }
        })
    }
    initWithAPI(){
        var self = this;
        var typingTimer;
        var loadingAPI = false;
        var option = {
            tags: self.tags,
            multiple: self.multiple,
            allowClear: true, 
            tokenSeparators: [','], 
            minimumResultsForSearch: 10, 
            placeholder: self.placeholder,
            minimumInputLength: self.minimumInputLength,
            query: function (query) {
                clearTimeout(typingTimer);
                if (query && !loadingAPI && self.api) {
                    var body = self.api.body;
                    if (query.term && body)
                        body.query = query.term;
                    typingTimer = setTimeout(function() {
                        loadingAPI = true;
                        $.ajax({
                            method: self.api.method,
                            url: self.api.url,
                            crossDomain: true,
                            contentType: 'application/json',
                            data: JSON.stringify(body),
                        }).done(function(response) {
                            if (response.result) {
                                // console.log('Response', response.result);
                                // var data = results;
                                if (query && response.result) {
                                    query.callback({results: response.result});
                                }
                                loadingAPI = false;
                            }
                        });
                    }, 500);
                }
                
            },
            formatSelection: function format(item) { 
                return item[self.params.textField || 'name']; 
            },
            formatResult: self.formatFunc,
            initSelection : function (element, callback) {
                callback(self.initData);
            }
        };
        if (self.createSearchChoice) {
            option.createSearchChoice = self.createSearchChoice;
        }
        self.elm.select2(option);
    }
    initOnChange() {
        var self = this;
        self.elm.select2('val', []).on("change", function (e) {
            if (e.added) {
                if (self.isDynamic){
                    self.selectedText = e.added['name'];
                    self.selectedValue = e.added['value'];
                    self.selectedLabel = e.added['name'];
                } else {
                    self.selectedText = e.added[self.params.textField];
                    self.selectedValue = e.added[self.params.textField];
                    self.selectedLabel = e.added[self.params.textField];
                }
            }
            // If e.val Is Array
            if (Array.isArray(e.val)) {
                // Check If All Elements of e.val Can Be Parsed To Integer
                var data = e.val;
                var isInt = data.every(function (item) {
                    return !isNaN(item);
                });
                if (isInt) {
                    self.selectedId = data.map(function (item) {
                        return parseInt(item);
                    });
                } else {
                    self.selectedId = data;
                }
            } else {
                // If e.val Is Not Array
                if (e.val) {
                    // Check If e.val Can Be Parsed To Integer
                    if (!isNaN(e.val)) {
                        self.selectedId = parseInt(e.val);
                    } else {
                        self.selectedId = e.val;
                    }
                } else {
                    self.selectedId = null;
                }
            }
            if (!self.selectedId) {
                self.selectedText = '';
            }
            self.onChange(self.selectedId, self.selectedText, self.selectedValue, self.selectedLabel);
        })
    }
};