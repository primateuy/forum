/** @odoo-module */

import Widget from "@web/legacy/js/core/widget";
import { jsonrpc } from "@web/core/network/rpc_service";
import { _t } from "@web/core/l10n/translation";
import IZIViewDashboardBlock from "@izi_dashboard/js/component/main/izi_view_dashboard_block";
import IZIViewVisual from "@izi_dashboard/js/component/main/izi_view_visual";
import IZIAutocomplete from "@izi_dashboard/js/component/general/izi_autocomplete";
var IZIViewDashboard = Widget.extend({
    template: 'IZIViewDashboard',
    events: {
        'click input': '_onClickInput',
        'click button': '_onClickButton',
        'click .izi_view_dashboard_ask_bg': '_onClickBgDashboardAsk',
        'click .izi_view_analysis_dialog_bg': '_onClickBgDashboardAnalysisDialog',
        'click .izi_view_dashboard_ask_btn': '_onClickSubmitAsk',
        'keydown .izi_view_dashboard_ask_input': '_onKeydownInputAsk',
        'click .code_execution': '_onClickExecuteCode',
        'click .izi_view_dashboard_ask_result_configuration': '_onClickAskResultConfiguration',
        'click .izi_view_dashboard_ask_result_add_to_dashboard': '_onClickAskResultAddToDashboard',
        'click .message_refresh': '_onClickMessageRefresh',
        'click .quick_message': '_onClickQuickMessage',
        'click .clear_message': '_onClickClearMessage',
        'click .izi_view_dashboard_ask_header_table': '_onClickHeaderTable',
        'click': '_globalClick',
        'dragenter': '_onDragEnterFileUploader',
        'dragover #izi_dashboard_file_uploader': '_onDragOverFileUploader',
        'dragleave #izi_dashboard_file_uploader': '_onDragLeaveFileUploader',
        'drop #izi_dashboard_file_uploader': '_onDropFileUploader',
    },

    /**
     * @override
     */
    init: function (parent) {
        this._super.apply(this, arguments);

        this.parent = parent;
        this.context = false;
        if (parent && parent.context) {
            this.context = parent.context;
        }
        this.$grid;
        this.$editor;
        this.$editorContainer;
        this.selectedDashboard;
        this.$blocks = [];
        this.default_ai_messages = [{
            'role': 'assistant',
            'content': `Hello! I am your AI Data Consultant. Feel free to ask me anything about data analytics. I can help you explore your data and generate new analysis. How can I assist you today?`,
        }];
        this.ai_messages = this.default_ai_messages.slice();
        this.raw_messages = this.default_ai_messages.slice();
        this.quick_messages = [];
        this.default_quick_messages = [
            'What analysis can you generate?',
            'Drill down!',
            'Elaborate the insights.',
            'Great!',
        ];
        this.askAnalysisId;
        this.$askVisual;
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

        // File Uploader
        self.$viewDashboardFileUploader = self.$('#izi_dashboard_file_uploader');

        // Dashboard Ask
        self.$viewDashboardAsk = self.$('.izi_view_dashboard_ask');
        self.$viewDashboardAskContainer = self.$('.izi_view_dashboard_ask_container');
        self.$viewDashboardAskChart = self.$('.izi_view_dashboard_ask_result_chart');
        self.$viewDashboardAskQuickMessages = self.$('.izi_view_dashboard_ask_quick_messages');
        self.default_quick_messages.forEach(function(msg) {
            self.quick_messages.push(msg);
        });
        self._renderQuickMessages();
        self._generateTableOptions();
    },
    _generateTableOptions: function(){
        var self = this
        var filterElm = self.$el.find('#custom_table_selection')
        var $dF = new IZIAutocomplete(self, {
            elm: filterElm,
            multiple: false,
            placeholder: "Select Table",
            minimumInput: false,
            noAllOption: true,
            params: {
                getTable:true,
                limit:10,
            },
            onChange: function (id, name, value) {
                self._updateDashboardTable(id)
            },
        });
    },
    _updateDashboardTable: function(table_id) {
        var self = this
        jsonrpc('/web/dataset/call_kw/izi.dashboard/update_dashboard_table', {
            model: 'izi.dashboard',
            method: 'update_dashboard_table',
            args: [self.selectedDashboard,table_id],
            kwargs: {},
        })
    },
    _onClickAskResultAddToDashboard: function(ev) {
        var self = this;
        new swal({
            title: "Confirmation",
            text: `
            Are you sure you want to add this analysis to your dashboard?
            `,
            icon: "warning",
            showCancelButton: true,
            confirmButtonText: 'Yes',
            heightAuto: false,
        }).then((result) => {
            if (result.isConfirmed) {
                if (self.selectedDashboard) {
                    jsonrpc('/web/dataset/call_kw/izi.dashboard/action_add_to_dashboard', {
                        model: 'izi.dashboard',
                        method: 'action_add_to_dashboard',
                        args: [self.selectedDashboard],
                        kwargs: {},
                    }).then(function (result) {
                        if (result.status == 200) {
                            if (result.analysis_id) {
                                self._getOwl().action.doAction({
                                    type: 'ir.actions.act_window',
                                    name: _t('Analysis'),
                                    target: 'new',
                                    res_id: result.analysis_id,
                                    res_model: 'izi.analysis',
                                    views: [[false, 'form']],
                                    context: {
                                    },
                                }, {
                                    onClose: function () {
                                        self._loadDashboard();
                                    },
                                });
                            }
                        } else {
                            if (result.status == 401) {
                                new swal('Need Access', result.message, 'warning');
                            } else
                                new swal('Error', result.message || result.error, 'error');
                        }
                    });
                }
            }
        })
    },

    _onClickAskResultConfiguration: function(ev) {
        var self = this;
        if (self.askAnalysisId) {
            self._getOwl().action.doAction({
                type: 'ir.actions.act_window',
                name: _t('Analysis'),
                target: 'new',
                res_id: self.askAnalysisId,
                res_model: 'izi.analysis',
                views: [[false, 'izianalysis']],
                context: {'analysis_id': self.askAnalysisId},
            },{
                onClose: function(){
                    if (self.$askVisual)
                        self.$askVisual._renderVisual();
                }
            });
        }
    },

    _globalClick: function(ev) {
        if (!$(ev.target).closest('.drilldown-fields').length) {
            $('.drilldown-fields').remove();
        }
    },

    _openAnalysisDialogById: function(analysisId) {
        var self = this;
        self.$viewDashboardAnalysisDialog.closest('.izi_dialog').show();
        var args = {
            'id': -1,
            'analysis_id': analysisId,
            'analysis_name': 'Analysis',
            'animation': true,
            'filters': [],
            'refresh_interval': false,
            'index': -1,
            'mode': false,
            'visual_type_name': '',
            'rtl': false,
        }
        var $blockDialog = new IZIViewDashboardBlock(self, args);
        $blockDialog.appendTo(self.$viewDashboardAnalysisDialog);
    },

    _openAnalysisById: function (analysisId) {
        var self = this;
        if (analysisId) {
            self._getOwl().action.doAction({
                type: 'ir.actions.act_window',
                name: _t('Analysis'),
                target: 'new',
                res_id: self.askAnalysisId,
                res_model: 'izi.analysis',
                views: [[false, 'izianalysis']],
                context: {'analysis_id': self.askAnalysisId},
            },{
                onClose: function(){
                    if (self.$askVisual)
                        self.$askVisual._renderVisual();
                }
            });
        }
    },

    _onClickHeaderTable: function(ev) {
        var self = this;
        if (self.selectedDashboard) {
            self._getOwl().action.doAction({
                type: 'ir.actions.act_window',
                name: _t('Dashboard'),
                target: 'new',
                res_id: self.selectedDashboard,
                res_model: 'izi.dashboard',
                views: [[false, 'form']],
                context: {},
            },{
                onClose: function(){
                    if (self.parent && self.parent.$configDashboard)
                        self.parent.$configDashboard._initDashboard();
                }
            });
        }
    },

    _generateAskChart: function(analysisId, analysisConfig) {
        var self = this;
        if (analysisId) {
            self.askAnalysisId = analysisId;
            self.analysisConfig = analysisConfig;
            var args = {
                'block_id': 'ask',
                'analysis_id': analysisId,
                'ask_chart': true,
            }
            // Deprecated, User Filters In Analysis
            // if (analysisConfig && analysisConfig.filters) {
            //     args.filters = {}
            //     args.filters.action = analysisConfig.filters;
            // }
            var $visual = new IZIViewVisual(self, args);
            self.$viewDashboardAskChart.empty();
            $visual.appendTo($(self.$viewDashboardAskChart));
            self.$askVisual = $visual;
        }
    },

    _onClickExecuteCode: function(ev) {
        var self = this;
        ev.stopPropagation();
        if ($(ev.currentTarget) && $(ev.currentTarget).closest('.code_content_sql')) {
            var query = $(ev.currentTarget).closest('.code_content_sql').text();
            query = query.replaceAll('play_arrow', '');
            if (query && self.selectedDashboard) {
                jsonrpc('/web/dataset/call_kw/izi.dashboard/action_execute_code', {
                    model: 'izi.dashboard',
                    method: 'action_execute_code',
                    args: [self.selectedDashboard, query],
                    kwargs: {},
                }).then(function (result) {
                    if (result.status == 200) {
                        if (result.id) {
                            self._generateAskChart(result.id);
                        }
                    } else {
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
                            new swal('Error', result.message || result.error, 'error');
                    }
                });
            }
        }
    },

    _onClickQuickMessage: function(ev) {
        var self = this;
        var message = $(ev.currentTarget).text();
        if (message) {
            self.$('.izi_view_dashboard_ask_input').val(message);
            self.quick_messages = [];
            self._renderQuickMessages();
            self._onClickSubmitAsk();
        }
    },

    _onClickClearMessage: function(ev) {
        var self = this;
        self.$viewDashboardAsk.empty();
        self.$viewDashboardAskChart.empty();
        self.ai_messages = self.default_ai_messages.slice();
        self.raw_messages = self.default_ai_messages.slice();
        self._renderAIMessages();
        self.quick_messages = [];
        self.default_quick_messages.forEach(function(msg) {
            self.quick_messages.push(msg);
        });
        self._renderQuickMessages();
    },

    _renderQuickMessages: function() {
        var self = this;
        self.$viewDashboardAskQuickMessages.empty();
        self.quick_messages.forEach(msg => {
            self.$viewDashboardAskQuickMessages.append(`
                <div class="quick_message">${msg}</div>
            `);
        });
        self.$viewDashboardAskQuickMessages.append(`
            <div class="clear_message">Clear All</div>
        `);
    },

    _renderAIMessages: function() {
        var self = this;
        self.$viewDashboardAsk.empty();
        var lastRole = false;
        var message_index = 0;
        self.ai_messages.forEach(msg => {
            var role = msg.role;
            if (role == 'assistant' || role == 'user') {
                var role_name = (role == 'assistant') ? 'Consultant' : 'You';
                var style = (role == 'assistant') ? `background: url('/izi_dashboard/static/description/icon_avatar.png');background-size: contain;` : 'background: #875A7B';
                var initial = (role == 'assistant') ? '' : 'U';
                var message_content = msg.content;
                if (lastRole != role) {
                    if (role == 'user' || message_index == 0) {
                        self.$viewDashboardAsk.append(`
                            <div class="role_section">
                                <div class="role_avatar" style="${style}">${initial}</div>
                                <div class="role_name">${role_name}</div>
                            </div>
                        `);
                    } else {
                        self.$viewDashboardAsk.append(`
                            <div class="role_section">
                                <div class="role_avatar" style="${style}">${initial}</div>
                                <div class="role_name">${role_name}</div>
                                <div class="message_refresh" data-index="${message_index}">
                                    <span class="material-icons">refresh</span>
                                </div>
                            </div>
                        `);
                    }
                    lastRole = role;
                }
                self.$viewDashboardAsk.append(`
                        <div class="message_section">
                            <div class="message_content" style="white-space:pre-wrap;">${message_content}</div>
                        </div>
                `)
            }
            message_index += 1;
        });
        self.$viewDashboardAsk.animate({
            scrollTop: self.$viewDashboardAsk.get(0).scrollHeight
        }, 1000);
    },

    _onClickMessageRefresh: function(ev) {
        var self = this;
        var messageIndex = $(ev.currentTarget).attr('data-index');
        if (messageIndex && messageIndex > 0) {
            self.ai_messages = self.ai_messages.slice(0, messageIndex);
            self.raw_messages = self.raw_messages.slice(0, messageIndex);
            self._renderAIMessages();
            self._onClickSubmitAsk();
        }
    },

    _onClickSubmitAsk: function(ev) {
        var self = this;
        var message_content = self.$('.izi_view_dashboard_ask_input').val();
        if (message_content) {
            self.ai_messages.push({
                'role': 'user',
                'content': message_content,
            })
            self._renderAIMessages();
            self.$('.izi_view_dashboard_ask_input').val('');
            self.raw_messages.push({
                'role': 'user',
                'content': message_content,
            })
        }

        // Submit To AI
        if (self.selectedDashboard && self.raw_messages) {
            let spinner = $(`<span class="spinner-border spinner-border-small" style="margin-top: 20px;"/>`);
            spinner.appendTo(self.$viewDashboardAsk);
            jsonrpc('/web/dataset/call_kw/izi.dashboard/action_get_lab_ask', {
                model: 'izi.dashboard',
                method: 'action_get_lab_ask',
                args: [self.selectedDashboard, self.raw_messages],
                kwargs: {},
            }).then(function (result) {
                self.$viewDashboardAsk.find('.spinner-border').remove();
                if (result.status == 200) {
                    if (result.new_messages) {
                        result.new_messages.forEach(function(msg) {
                            self.ai_messages.push({
                                'role': msg.role,
                                'content': msg.content,
                            })
                        });
                        if (result.analysis_id) {
                            self._generateAskChart(result.analysis_id, result.analysis_config);
                            self.$viewDashboardAskContainer.find('.izi_view_dashboard_ask_result_title').show();
                        }
                        self._renderAIMessages();
                    }
                    if (result.raw_messages) {
                        self.raw_messages = result.raw_messages;
                    }
                    if (result.quick_messages && result.quick_messages.length > 0) {
                        self.quick_messages = result.quick_messages;
                    } else {
                        self.quick_messages = [];
                        self.default_quick_messages.forEach(function(msg) {
                            self.quick_messages.push(msg);
                        });
                    }
                    self._renderQuickMessages();
                } else {
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
                    } else if (result.status == 500) {
                        new swal('Error', result.message, 'error');
                    } else
                        new swal('Error', result.message, 'error');
                }
            }); 
        }
    },

    _onKeydownInputAsk: function(ev) {
        var self = this;
        if (self.$('.izi_view_dashboard_ask_input').is(':focus') && (ev.keyCode == 13) && (!ev.shiftKey)) {
            ev.preventDefault();
            self._onClickSubmitAsk();
        }
    },

    _onClickBgDashboardAsk: function(ev) {
        var self = this;
        self.$viewDashboardAsk.closest('.izi_dialog').hide();
    },

    _onClickBgDashboardAnalysisDialog: function(ev) {
        var self = this;
        self.$viewDashboardAnalysisDialog.closest('.izi_dialog').hide();
    },

    _getViewVisualByAnalysisId: function(analysis_id) {
        var self = this;
        var view_visual = false;
        self.$blocks.forEach(function (block) {
            if (block.analysis_id == analysis_id) {
                view_visual = block.$visual;
            }
        });
        if (self.$askVisual && self.$askVisual.analysis_id == analysis_id) {
            view_visual = self.$askVisual;
        }
        return view_visual;
    },

    _onDragEnterFileUploader: function(ev) {
        var self = this;
        if (self.$el.hasClass('izi_edit_mode')) return;
        ev.stopPropagation();
        ev.preventDefault();
        self.$viewDashboardFileUploader.fadeIn(100);
    },

    _onDragOverFileUploader: function(ev) {
        var self = this;
        if (self.$el.hasClass('izi_edit_mode')) return;
        ev.stopPropagation();
        ev.preventDefault();
        self.$viewDashboardFileUploader.fadeIn(100);
    },

    _onDragLeaveFileUploader: function(ev) {
        var self = this;
        if (self.$el.hasClass('izi_edit_mode')) return;
        ev.stopPropagation();
        ev.preventDefault();
        self.$viewDashboardFileUploader.fadeOut(100, function() {
            self.$viewDashboardFileUploader.hide();
        });
    },

    _onDropFileUploader: function(ev) {
        var self = this;
        if (self.$el.hasClass('izi_edit_mode')) return;
        ev.preventDefault();
        var files = ev.originalEvent.dataTransfer.files;
        var filename = '';
        var filetype = '';
        if (files && files.length) {
            filename = files[0].name;
            filetype = files[0].type;
        }
        var fileReader = new FileReader();
        fileReader.onload = function(){
            var fileContent = fileReader.result;
            // console.log(files, filename, filetype, fileContent);
            if (filetype == 'application/json') {
                jsonrpc('/web/dataset/call_kw/izi.dashboard.config.wizard/process_wizard_model', {
                    model: 'izi.dashboard.config.wizard',
                    method: 'process_wizard_model',
                    args: [self.selectedDashboard, fileContent],
                    kwargs: {},
                }).then(function (result) {
                    if (result.status == 200) {
                        self.parent.$configDashboard._initDashboard();
                    } else {
                        if (result.status == 401) {
                            new swal('Need Access', result.message, 'warning');
                        } else
                            new swal('Error', result.message, 'error');
                    }
                });
            } else if (filetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' || filetype == 'application/vnd.ms-excel' || filetype == 'text/csv') {
                if (filetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' || filetype == 'application/vnd.ms-excel') {
                    var workbook = XLSX.read(fileContent, {
                        type: 'binary',
                      });
                    fileContent = XLSX.write(workbook, {
                        type: 'base64',
                    });
                } else if (filetype == 'text/csv') {
                    
                }
                jsonrpc('/web/dataset/call_kw/izi.data.source.item/process_data_file', {
                    model: 'izi.data.source.item',
                    method: 'process_data_file',
                    args: [self.selectedDashboard, filename, filetype, fileContent],
                    kwargs: {},
                }).then(function (result) {
                    if (result.status == 200) {
                        self.parent.$configDashboard._initDashboard();
                    } else {
                        if (result.status == 401) {
                            new swal('Need Access', result.message, 'warning');
                        } else
                            new swal('Error', result.message, 'error');
                    }
                });
            }
        }
        if (filetype == 'application/json') {
            fileReader.readAsText(files[0]);
        } else if (filetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' || filetype == 'application/vnd.ms-excel' || filetype == 'text/csv') {
            fileReader.readAsBinaryString(files[0]);
        } else {
            new swal('Error', 'Unsupported file types (only support JSON, CSV, XLSX)', 'error');
        }
        self.$viewDashboardFileUploader.fadeOut(500, function() {
            self.$viewDashboardFileUploader.hide();
        });
    },

    /**
     * Private Method
     */
    _setDashboard: function(dashboard_id) {
        var self = this;
        self.selectedDashboard = dashboard_id;
    },
    _loadDashboard: function (filters, mode=false) {
        var self = this;
        self._clear();
        if (self.selectedDashboard) {
            $('#global_dashboard_id').val(self.selectedDashboard)
            jsonrpc('/web/dataset/call_kw/izi.dashboard.block/search_read', {
                model: 'izi.dashboard.block',
                method: 'search_read',
                args: [[['dashboard_id', '=', self.selectedDashboard]], ['id', 'gs_x', 'gs_y', 'gs_w', 'gs_h', 'min_gs_w', 'min_gs_h', 'analysis_id', 'animation', 'refresh_interval', 'visual_type_name', 'rtl']],
                kwargs: {},
            }).then(function (res) {
                // console.log('Load Dashboard', res);
                self.dashboardBlocks = res;
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
                    if (mode == 'ai_analysis') {
                        if (isScoreCard) {
                            block.gs_x = 0;
                            block.gs_h = 3;
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
                    if (window.innerWidth <= 792 || mode == 'ai_analysis') {
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
                            'filters': filters,
                            'refresh_interval': block.refresh_interval,
                            'index': index,
                            'mode': mode,
                            'visual_type_name': block.visual_type_name,
                            'rtl': block.rtl,
                        }
                        index += 1;
                        var $block = new IZIViewDashboardBlock(self, args);
                        $block.appendTo($(`.grid-stack-item[gs-id="${block.id}"] .grid-stack-item-content`));
                        self.$blocks.push($block);
                    }
                });
            });
        }
    },

    _clear() {
        var self = this;
        self.$blocks.forEach($block => {
            $block.clearInterval();
            $block.destroy();
        })
        self.$blocks = [];
    },

    _removeItem(id) {
        this.$grid.engine.nodes = (this.$grid.engine.nodes).filter(object => {
            return object.id !== id;
            });
        $(`.grid-stack-item[gs-id="${id}"]`).remove();
    },

    _onClickInput: function(ev) {
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

export default IZIViewDashboard;