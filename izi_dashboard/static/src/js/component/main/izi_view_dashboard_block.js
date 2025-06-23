/** @odoo-module */

import Widget from "@web/legacy/js/core/widget";
import { _t } from "@web/core/l10n/translation";
import { jsonrpc } from "@web/core/network/rpc_service";
import { useService } from "@web/core/utils/hooks";

import IZIViewVisual from "@izi_dashboard/js/component/main/izi_view_visual";
import IZISelectFilterTemp from "@izi_dashboard/js/component/main/izi_select_filter_temp";
var IZIViewDashboardBlock = Widget.extend({
    template: 'IZIViewDashboardBlock',
    events: {
        'click input': '_onClickInput',
        'click .izi_dashboard_block_content': '_onClickContent',
        'click .izi_action_open_analysis': '_openAnalysis',
        'click .izi_action_quick_open_analysis': '_quickOpenAnalysis',
        'click .izi_action_edit_analysis': '_editAnalysis',
        'click .izi_action_open_list_view': '_openListView',
        'click .izi_action_delete_block': '_onClickDeleteBlock',
        'click .izi_action_export_config': '_onClickExportConfig',
        'click .izi_action_duplicate_block': '_onClickDuplicateBlock',
        'click .izi_action_export_excel': '_onClickExportExcel',
        'click .izi_btn_speech_ai': '_onClickSpeechAI',
        'mouseover .izi_btn_speech_ai': '_mouseOverSpeechAI',
        'mouseout .izi_btn_speech_ai': '_mouseOutSpeechAI',
        'click .izi_dashboard_block_description': '_onClickBlockDescription',
    },

    /**
     * @override
     */
    init: function (parent, args) {
        this._super.apply(this, arguments);

        this.parent = parent;
        this.context = false;
        if (parent && parent.context) {
            this.context = parent.context;
        }
        this.id = args.id;
        this.analysis_name = args.analysis_name;
        this.analysis_id = args.analysis_id;
        this.animation = args.animation;
        this.refresh_interval = args.refresh_interval;
        this.filters = args.filters;
        this.index = args.index;
        this.mode = args.mode;
        this.rtl = args.rtl;
        this.args = {}
        this.$visual;
        this.$title;
        this.$filter;
        this.$description;
        this.$speech_ai;
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
        self.args = {
            'block_id': self.id,
            'analysis_id': self.analysis_id,
            'filters': self.filters,
            'refresh_interval': self.refresh_interval,
            'index': self.index,
            'mode': self.mode,
            'rtl': self.rtl,
        }
        
        if (self.animation) {
            am4core.useTheme(am4themes_animated);
        } else {
            am4core.unuseTheme(am4themes_animated);
        }

        self.$title = self.$el.find('.izi_dashboard_block_header .izi_dashboard_block_title');
        self.$description = $(`<div class="izi_dashboard_block_description"></div>`);
        self.$speech_ai = $(`
        <div class="izi_btn izi_btn_speech_ai px-2">
            <span class="material-icons izi_btn_icon">volume_up</span>
            <audio></audio>
        </div>`);
        if (self.mode == 'ai_analysis') {
            self.$el.find('.izi_dashboard_block_content').addClass('izi_mode_analysis');
            self.$description.appendTo(self.$el.find('.izi_dashboard_block_content'));
            self.$speech_ai.appendTo(self.$el.find('.izi_dashboard_block_content')).hide();
        }
        self.$visual = new IZIViewVisual(self, self.args);
        self.$visual.appendTo(self.$el.find('.izi_dashboard_block_content'));
        
        // Add Component Filters
        self.$filter = new IZISelectFilterTemp(self, self.$visual);
        self.$filter.appendTo(self.$el.find('.izi_dashboard_block_header'));
        if (self.analysis_id) {
            self.$filter.analysis_id = self.analysis_id;
            self.$filter._loadFilters();
        }
    },

    clearInterval: function() {
        var self = this;
        if (self.$visual && self.$visual.interval) {
            clearInterval(self.$visual.interval);
        }
    },

    destroy: function() {
        var self = this;
        self.$el.remove();
    },

    _getViewVisualByAnalysisId: function(analysis_id) {
        var self = this;
        if (self.parent && self.parent._getViewVisualByAnalysisId)
            return self.parent._getViewVisualByAnalysisId(analysis_id);
        return false;
    },

    /**
     * Private Method
     */
    _resetArgs: function() {
        var self = this;
        self.args = {
            'block_id': self.id,
            'analysis_id': self.analysis_id,
            'filters': self.filters,
            'refresh_interval': self.refresh_interval,
            'index': self.index,
            'mode': self.mode,
            'rtl': self.rtl,
        }
    },

    _onClickInput: function (ev) {
        var self = this;
    },

    _onClickBlockDescription: function (ev) {
        ev.stopPropagation();
    },
    
    _onClickSpeechAI: function(ev) {
        ev.stopPropagation();
        ev.preventDefault();
        var self = this;
        if (self.analysis_id) {
            let speechAI = 'speech_ai_' + self.analysis_id;
            let btnSpeechAI = $(ev.currentTarget).attr('id', speechAI);

            // check and get speech ai audio
            if (!btnSpeechAI.find('audio').attr('src')) {
                btnSpeechAI.find('.izi_btn_icon').hide();
                if (!btnSpeechAI.hasClass('generated-speech')) {
                    let spinner = $(`<span class="spinner-border spinner-border-small"/>`);
                    spinner.appendTo(btnSpeechAI);
                    btnSpeechAI.addClass('generated-speech');

                    jsonrpc('/web/dataset/call_kw/izi.analysis/action_get_lab_speech_ai', {
                        model: 'izi.analysis',
                        method: 'action_get_lab_speech_ai',
                        args: [self.analysis_id],
                        kwargs: {},
                    }).then((result) => {
                        btnSpeechAI.find('.spinner-border').remove();
                        btnSpeechAI.find('.izi_btn_icon').show();
                        btnSpeechAI.addClass('playing');
        
                        let binaryData = result.ai_speech;
        
                        // Create Blob URL
                        const byteCharacters = atob(binaryData);
                        const byteArrays = [];
                        for (let i = 0; i < byteCharacters.length; i++) {
                            byteArrays.push(byteCharacters.charCodeAt(i));
                        }
                        const byteArray = new Uint8Array(byteArrays);
                        let blob = new Blob([byteArray], { type: 'audio/mpeg' });
                        let blobUrl = URL.createObjectURL(blob);
                        btnSpeechAI.find('audio').prop('src', blobUrl)[0].play();
                    });
                }
            } else {
                let btnSpeechAudio = btnSpeechAI.find('audio')[0];
                if (btnSpeechAudio.paused) {
                    btnSpeechAudio.play();
                    btnSpeechAI.addClass('playing');
                    btnSpeechAI.removeClass('paused');
                    btnSpeechAI.children().html('volume_up');
                } else {
                    btnSpeechAudio.pause();
                    btnSpeechAI.removeClass('playing');
                    btnSpeechAI.addClass('paused');
                    btnSpeechAI.children().html('pause');
                };
            };
            btnSpeechAI.find('audio')[0].addEventListener('ended', function() {
                btnSpeechAI.removeClass('playing');
            });
        };
    },

    _mouseOverSpeechAI: function(ev) {
        var self = this;
        let btnSpeechAI = $(ev.currentTarget);
        let audioSpeechAI = btnSpeechAI.find('audio');
        if (audioSpeechAI.attr('src')) {
            if (audioSpeechAI[0].paused) {
                btnSpeechAI.children().html('volume_up');
            } else {
                btnSpeechAI.children().html('pause');
            }
        }
    },

    _mouseOutSpeechAI: function(ev) {
        var self = this;
        let btnSpeechAI = $(ev.currentTarget);
        let audioSpeechAI = btnSpeechAI.find('audio');
        if (audioSpeechAI.attr('src')) {
            if (audioSpeechAI[0].paused) {
                btnSpeechAI.children().html('pause');
            } else {
                btnSpeechAI.children().html('volume_up');
            }
        }
    },

    _onClickExportExcel: function(ev) {
        var self = this;
        var id = $(ev.currentTarget).data('id');
        if (id) {
            var base_url = window.location.origin;
            if (self.$visual) {
                var filters = JSON.stringify(self.$visual._getFilters());
                var url = `${base_url}/izi/excel/${id.toString()}?filters=${filters}`;
                if (self.context) {
                    if ('allowed_company_ids' in self.context) {
                        var allowed_company_ids = self.context['allowed_company_ids']
                        if (allowed_company_ids != '' && allowed_company_ids != null && allowed_company_ids != false && allowed_company_ids != undefined) {
                            url = `${base_url}/izi/excel/${id.toString()}?filters=${filters}&allowed_company_ids=[${self.context['allowed_company_ids']}]`;
                        }
                    }
                }
                window.open(url, '_blank');
            }
        }
    },

    _onClickDuplicateBlock: function (ev) {
        var self = this;
        var id = $(ev.currentTarget).data('id');
        if (id) {
            new swal({
                title: "Duplicate Analysis",
                text: `
                    Do you confirm to duplicate the analysis ?
                `,
                icon: "warning",
                showCancelButton: true,
                confirmButtonText: 'Yes',
                heightAuto : false,
            }).then((result) => {
                if (result.isConfirmed) {
                    jsonrpc('/web/dataset/call_kw/izi.dashboard.block/action_copy', {
                        model: 'izi.dashboard.block',
                        method: 'action_copy',
                        args: [[id]],
                        kwargs: {},
                    }).then(function (res) {
                        self.parent._loadDashboard();
                    })
                }
            });
        }
    },

    _onClickExportConfig: function (ev) {
        var self = this;
        var block_id = $(ev.currentTarget).data('id');
        jsonrpc('/web/dataset/call_kw/izi.analysis/export_config', {
            model: 'izi.analysis',
            method: 'export_config',
            args: [[self.analysis_id], block_id],
            kwargs: {},
        }).then(function (attachment_id) {
            window.open('/web/content/' + attachment_id + '?download=true', '_blank');
        });
    },
    _onClickDeleteBlock: function (ev) {
        var self = this;
        var id = $(ev.currentTarget).data('id');
        if (id) {
            new swal({
                title: "Remove Analysis",
                text: `
                    Do you confirm to remove the analysis ?
                `,
                icon: "warning",
                showCancelButton: true,
                confirmButtonText: 'Yes',
                heightAuto : false,
            }).then((result) => {
                if (result.isConfirmed) {
                    jsonrpc('/web/dataset/call_kw/izi.dashboard.block/unlink', {
                        model: 'izi.dashboard.block',
                        method: 'unlink',
                        args: [[id]],
                        kwargs: {},
                    }).then(function (res) {
                        self.parent._removeItem(id);
                        new swal('Success', `The analysis has been removed \n from this dashboard successfully`, 'success');
                    })
                }
            });
        }
    },

    _openAnalysis: function () {
        var self = this;
        if (self.analysis_id) {
            self._getOwl().action.doAction({
                type: 'ir.actions.act_window',
                name: _t('Analysis'),
                target: 'current',
                res_id: self.analysis_id,
                res_model: 'izi.analysis',
                views: [[false, 'izianalysis']],
                context: {'analysis_id': self.analysis_id},
            });
        }
    },

    _quickOpenAnalysis: function () {
        var self = this;
        if (self.analysis_id) {
            self._getOwl().action.doAction({
                type: 'ir.actions.act_window',
                name: _t('Analysis'),
                target: 'new',
                res_id: self.analysis_id,
                res_model: 'izi.analysis',
                views: [[false, 'izianalysis']],
                context: {'analysis_id': self.analysis_id},
            },{
                onClose: function(){
                    self._resetArgs();
                    self.$visual._renderVisual(self.args);
                }
            });
        }
    },

    _editAnalysis: function () {
        var self = this;
        if (self.analysis_id) {
            self._getOwl().action.doAction({
                type: 'ir.actions.act_window',
                name: _t('Analysis'),
                target: 'new',
                res_id: self.analysis_id,
                res_model: 'izi.analysis',
                views: [[false, 'form']],
                context: { 'active_test': false },
            }, {
                onClose: function () {
                    self._resetArgs();
                    self.$visual._renderVisual(self.args)
                },
            });
        }
    },

    _onClickContent: function (ev) {
        var self = this;
        // Find if the content has scorecard inside
        if ($(ev.currentTarget).find('.scorecard').length > 0) {
            self._openListView();
        }
    },

    _openListView: function() {
        var self = this;
        var args = self.args
        args['filters'] = self.$visual.filters
        if (self.analysis_id && self.mode != 'ai_analysis') {
            jsonrpc('/web/dataset/call_kw/izi.analysis/ui_get_view_parameters', {
                model: 'izi.analysis',
                method: 'ui_get_view_parameters',
                args: [[self.analysis_id], self.args],
                kwargs: { context: self.context},
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

export default IZIViewDashboardBlock;