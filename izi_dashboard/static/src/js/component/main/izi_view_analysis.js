/** @odoo-module */

import Widget from "@web/legacy/js/core/widget";

import IZIViewVisual from "@izi_dashboard/js/component/main/izi_view_visual";
import IZISelectFilterTemp from "@izi_dashboard/js/component/main/izi_select_filter_temp";
import { jsonrpc } from "@web/core/network/rpc_service";
import { useService } from "@web/core/utils/hooks";
var IZIViewAnalysis = Widget.extend({
    template: 'IZIViewAnalysis',
    events: {
        'click .izi_view_analysis_explore_container': '_onClickAnalysisExpore',
        'click .izi_submit_analysis_explore': '_onClickSubmitAnalysisExpore',
        'click .izi_view_analysis_explore_bg': '_onClickBgAnalysisExpore',
        'click .izi_update_script': '_onClickUpdateScript',
        'click .izi_close_script': '_onClickCloseScript',
        'click .izi_dashboard_script_close': '_onClickCloseScript',
        'click .izi_toggle_float_script': '_onClickToggleFloatScript',
        'click .izi_script_ai': '_onClickContinueScriptAI',
        'click #izi_tab_js': '_onClickShowJsScript',
        'click #izi_tab_css': '_onClickShowCssScript',
    },

    /**
     * @override
     */
    init: function (parent) {
        var self = this;
        this._super.apply(this, arguments);
        
        self.parent = parent;
        this.context = false;
        if (parent && parent.context) {
            this.context = parent.context;
        }
        self.$visual;
        self.$title;
        self.$filter;
        self.analysis_id;
        self.selectedAnalysisExplores = [];
        self.selectedDashboardExplore;
        self.$editor;
        self.$editorCss;
        self.$editorContainer;
        self.lastScript = '';
        self.floatingScriptEditor = false;
        self.scriptEditorType = '';
        self.scriptType = '';
        self.lastGeneratedScript = '';
        self.lastError = '';
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

        am4core.useTheme(am4themes_animated);

        self.$title = self.$el.find('.izi_dashboard_block_header .izi_dashboard_block_title');
        
        // Add Component Visual View
        self.$visual = new IZIViewVisual(self);
        self.$visual.appendTo(self.$el.find('.izi_dashboard_block_content'));

        // Add Component Filters
        self.$filter = new IZISelectFilterTemp(self, self.$visual);
        self.$filter.appendTo(self.$el.find('.izi_dashboard_block_header'));

        // Analysis Explore
        self.$viewAnalysisExplore = self.$('.izi_view_analysis_explore');

        // Check If Opened In A Modal Dialog
        // Add Class If So
        setTimeout(function () {
            var $dialog = self.$el.closest('.modal-dialog');
            if ($dialog.length) {
                $dialog.addClass('izi_modal_dialog_full');
                $dialog.closest('.modal').attr('style', 'z-index: 10;');
            }
        }, 1000);
    },

    _getViewVisualByAnalysisId: function (analysis_id) {
        var self = this;
        if (self.$visual.analysis_id == analysis_id)
            return self.$visual;
        return false;
    },

    _setAnalysisId: function (analysis_id) {
        var self = this;
        self.analysis_id = analysis_id;
        if (self.$filter) {
            self.$filter.analysis_id = analysis_id;
            self.$filter._loadFilters();
        }
    },

    _onClickBgAnalysisExpore: function (ev) {
        var self = this;
        self.$viewAnalysisExplore.closest('.izi_dialog').hide();
    },

    _onClickAnalysisExpore: function (ev) {
        var self = this;
        var analysis_id = $(ev.currentTarget).data('analysis-id');
        if ($(ev.currentTarget).hasClass('active')) {
            $(ev.currentTarget).removeClass('active');
            // Check if analysis_id is in selectedAnalysisExplores
            var index = self.selectedAnalysisExplores.indexOf(analysis_id);
            if (index > -1) {
                self.selectedAnalysisExplores.splice(index, 1);
            }
        } else {
            $(ev.currentTarget).addClass('active');
            // Check if analysis_id is not in selectedAnalysisExplores
            var index = self.selectedAnalysisExplores.indexOf(analysis_id);
            if (index == -1) {
                self.selectedAnalysisExplores.push(analysis_id);
            }
            
        }
    },

    _onClickSubmitAnalysisExpore: function (ev) {
        var self = this;
        new swal({
            title: "Confirmation",
            text: `
                Do you confirm to save the selected analysis (${self.selectedAnalysisExplores.length})?
            `,
            icon: "warning",
            showCancelButton: true,
            confirmButtonText: 'Yes',
            heightAuto : false,
        }).then((result) => {
            if (result.isConfirmed) {
                // console.log(self.selectedAnalysisExplores);
                jsonrpc('/web/dataset/call_kw/izi.analysis/save_lab_analysis_explore', {
                    model: 'izi.analysis',
                    method: 'save_lab_analysis_explore',
                    args: [self.selectedAnalysisExplores, self.selectedDashboardExplore],
                    kwargs: {},
                }).then(function (result) {
                    new swal('Success', `Analysis has been successfully saved`, 'success');
                    self.$viewAnalysisExplore.closest('.izi_dialog').hide();
                });
            }
        });
    },

    _loadVisualScriptEditor: function () {
        var self = this;
        if(self.scriptEditorType == 'Python' || self.scriptEditorType == 'PostgreSQL'){
            self.$editorContainer.find('.izi_dashboard_script_type').attr('src', '/izi_dashboard/static/src/img/js.png');
        }
        // Query Editor
        ace.config.set('basePath', '/izi_dashboard/static/lib/ace-1.3.1/');
        ace.config.set('modePath', '/izi_dashboard/static/lib/ace-1.3.1/');
        ace.config.set('themePath', '/izi_dashboard/static/lib/ace-1.3.1/');
        ace.config.set('workerPath', '/izi_dashboard/static/lib/ace-1.3.1/');
        self.$editor = ace.edit('izi_script_editor', {
            fontSize: "12px",
            fontFamily: "JetBrainsMono",
        });
        self.$editor.setTheme('ace/theme/chrome');
        self.$editor.setOption({ 
            useWorker: false,
        });
        self.$editorCss = ace.edit('izi_script_editor_css', {
            fontSize: "12px",
            fontFamily: "JetBrainsMono",
        });
        self.$editorCss.setTheme('ace/theme/chrome');
        self.$editorCss.setOption({ 
            useWorker: false,
        });
        self._activateCustomCommand();
        self.scriptEditorType = 'Javascript';
        self.$editorCss.session.setMode('ace/mode/css');
        self.$editor.session.setMode('ace/mode/javascript');
        self.$editorContainer = self.$('.izi_dashboard_script_editor');
        self.$editorContainer.find('.izi_script_tab').removeClass("d-none")
        self.$editorContainer.draggable();
        self.$editorContainer.resizable();
        self.$editorContainer.removeClass('dark-mode');
        self.$editorContainer.addClass('light-mode');
        self._resetScriptEditor();
    },

    _loadDataScriptEditor: function (type) {
        var self = this;
        self._onClickShowJsScript()
        // Query Editor
        ace.config.set('basePath', '/izi_dashboard/static/lib/ace-1.3.1/');
        ace.config.set('modePath', '/izi_dashboard/static/lib/ace-1.3.1/');
        ace.config.set('themePath', '/izi_dashboard/static/lib/ace-1.3.1/');
        ace.config.set('workerPath', '/izi_dashboard/static/lib/ace-1.3.1/');
        self.$editor = ace.edit('izi_script_editor', {
            fontSize: "12px",
            fontFamily: "JetBrainsMono",
        });
        self.$editor.setTheme('ace/theme/monokai');
        self.$editor.setOption({ 
            useWorker: false,
        });
        self._activateCustomCommand();
        self.$editorContainer = self.$('.izi_dashboard_script_editor');
        if (type == 'python') {
            self.scriptEditorType = 'Python';
            self.$editor.session.setMode('ace/mode/python');
            self.$editorContainer.find('.izi_dashboard_script_type').attr('src', '/izi_dashboard/static/src/img/python.png');
        } else if (type == 'sql') {
            self.scriptEditorType = 'PostgreSQL';
            self.$editor.session.setMode('ace/mode/sql');
            self.$editorContainer.find('.izi_dashboard_script_type').attr('src', '/izi_dashboard/static/src/img/psql.png');
        }
        self.$editorContainer.find('.izi_script_tab').addClass("d-none")
        self.$editorContainer.find('#izi_script_editor').addClass("h-100")
        self.$editorContainer.draggable();
        self.$editorContainer.resizable();
        self.$editorContainer.removeClass('light-mode');
        self.$editorContainer.addClass('dark-mode');
        self.$editor.resize();
        self._resetScriptEditor();
    },

    _resetScriptEditor: function() {
        var self = this;
        if (self.$editorContainer) {
            self.$editorContainer.attr('style', '');

            // Title and Value
            self.$editorContainer.find('h4').text('');
            self.$editorContainer.find('.izi_update_script').attr('data-analysis-id', 0);
            self.$editorContainer.find('.izi_update_script').attr('data-analysis-name', '');
            self.$editorContainer.find('.izi_update_script').attr('data-block-id', 0);
            self.$editorContainer.find('.izi_update_script').attr('data-script-type', '');
            
            // Default Not Floating
            // self.$editorContainer.removeClass('floating');
            // self.$editorContainer.css('top', 'auto');
            // self.$editorContainer.css('bottom', 'auto');
            // self.$editorContainer.css('left', 'auto');
            // self.$editorContainer.css('right', 'auto');
            // self.floatingScriptEditor = false;

            // Default Floating
            self.$editorContainer.addClass('floating');
            self.$editorContainer.css('top', '30px');
            self.$editorContainer.css('bottom', '30px');
            self.$editorContainer.css('left', '10px');
            self.$editorContainer.css('right', '10px');
            self.$editorContainer.css('width', 'auto');
            self.$editorContainer.css('height', 'auto');
            self.floatingScriptEditor = true;

            // Resize
            self.$editor.resize();

            // Disable Scroll
            var $dialog = self.$el.closest('.modal-dialog');
            if ($dialog.length) {
                $dialog.addClass('izi_modal_dialog_no_scroll');
            }
        }
    },

    _closeScript : function () {
        var self = this;
        if (self.$editorContainer) {
            self.$editorContainer.hide();
            self._resetScriptEditor();
            // Enable Scroll
            var $dialog = self.$el.closest('.modal-dialog');
            if ($dialog.length) {
                $dialog.removeClass('izi_modal_dialog_no_scroll');
            }
        }
    },

    _onClickCloseScript: function () {
        var self = this;
        var script = self.$editor.getValue();
        if (script == self.lastScript) {
            self._closeScript();
        } else {
            new swal({
                title: "Close Script Editor",
                text: `
                    Do you confirm to close the script editor and discard the changes?
                `,
                icon: "warning",
                showCancelButton: true,
                confirmButtonText: 'Yes',
                heightAuto : false,
            }).then((result) => {
                if (result.isConfirmed) {
                    self._closeScript();
                }
            });
        }
    },

    _activateCustomCommand: function () {
        var self = this;
        if (self.$editor) {
            self.$editor.commands.addCommand({
                name: 'Ask GPT To Complete Code',
                bindKey: {
                    win: 'Ctrl-G',
                    mac: 'Command-G'
                },
                exec: function(editor) {
                    self._onClickContinueScriptAI();
                },
                readOnly: false,
            });
            self.$editor.commands.addCommand({
                name: 'Ask GPT General Question',
                bindKey: {
                    win: 'Ctrl-Shift-G',
                    mac: 'Command-Shift-G'
                },
                exec: function(editor) {
                    self._onClickContinueScriptAI();
                    // self._onClickGeneralScriptAI();
                },
                readOnly: false,
            });
            self.$editor.commands.addCommand({
                name: 'Save',
                bindKey: {
                    win: 'Ctrl-S',
                    mac: 'Command-S'
                },
                exec: function(editor) {
                    var script = self.$editor.getValue();
                    if (script != self.lastScript) {
                        self._onClickUpdateScript(undefined, false, function() {
                            self._onClickCloseScript();
                            // if (self.floatingScriptEditor)
                            //     self._onClickToggleFloatScript();
                        });
                    }
                },
                readOnly: true,
            });
            self.$editor.commands.addCommand({
                name: 'Save and Run',
                bindKey: {
                    win: 'Ctrl-Shift-S',
                    mac: 'Command-Shift-S'
                },
                exec: function(editor) {
                    var script = self.$editor.getValue();
                    if (script != self.lastScript) {
                        self._onClickUpdateScript(undefined, true, function() {
                            self._onClickCloseScript();
                            // if (self.floatingScriptEditor)
                            //     self._onClickToggleFloatScript();
                        });
                    }
                },
                readOnly: true,
            });
            self.$editor.commands.addCommand({
                name: 'Toggle Float',
                bindKey: {
                    win: 'Ctrl-B',
                    mac: 'Command-B'
                },
                exec: function(editor) {
                    self._onClickToggleFloatScript();
                },
                readOnly: true,
            });
        }
    },

    _onClickShowJsScript: function(ev) {
        var self = this
        $("#izi_tab_js").addClass("izi_tab_active")
        $("#izi_tab_css").removeClass("izi_tab_active")
        $("#izi_script_editor").removeClass("d-none")
        $('#izi_script_editor').removeClass("h-100")
        $("#izi_script_editor_css").addClass("d-none")
        $('.izi_dashboard_script_type').attr('src', '/izi_dashboard/static/src/img/js.png');
    },
    _onClickShowCssScript: function(ev) {
        var self = this
        $("#izi_tab_css").addClass("izi_tab_active")
        $("#izi_tab_js").removeClass("izi_tab_active")
        $("#izi_script_editor").addClass("d-none")
        $("#izi_script_editor_css").removeClass("d-none")
        $('.izi_dashboard_script_type').attr('src', '/izi_dashboard/static/src/img/css.png');
    },
    _onClickContinueScriptAI: function(ev, last_generated_code='', last_error_message='') {
        var self = this;
        if (self.$editor && self.analysis_id) {
            var cur_pos = self.$editor.getCursorPosition();
            var row = cur_pos.row;
            var col = cur_pos.column;
            var spaces = '';
            for (var i = 0; i < col; i++) {
                spaces += ' ';
            }
            var origin_code = '';
            var total_line = 0;
            while (row >= 0) {
                if (origin_code == '') {
                    origin_code = self.$editor.session.getLine(row);
                } else {
                    var line = self.$editor.session.getLine(row);
                    origin_code = line + '\n' + origin_code;
                }
                row--;
                total_line++;
                // if (total_line > 20)
                //     break;
            }
            
            var origin_after_code = '';
            var all_total_line = self.$editor.session.getLength();
            row = cur_pos.row;
            while (row <= all_total_line) {
                if (origin_after_code == '') {
                    origin_after_code = self.$editor.session.getLine(row);
                } else {
                    var line = self.$editor.session.getLine(row);
                    origin_after_code = origin_after_code + '\n' + line;
                }
                row++;
            }

            if (origin_code) {
                $('.spinner-container').addClass('d-flex');
                jsonrpc('/web/dataset/call_kw/izi.analysis/action_get_lab_script', {
                    model: 'izi.analysis',
                    method: 'action_get_lab_script',
                    args: [self.analysis_id, self.scriptEditorType, origin_code, origin_after_code, cur_pos.column, last_generated_code, last_error_message],
                    kwargs: {},
                }).then(function (result) {
                    $('.spinner-container').removeClass('d-flex');
                    if (result.status == 200) {
                        var code = '';
                        if (result.popup && result.code) {
                            self.lastError = '';
                            self.lastGeneratedScript = result.code;
                            new swal({
                                title: "The Fixed Code!",
                                html: `<pre style="text-align: left;">${result.code}</pre>`,
                                icon: "warning",
                                showCancelButton: true,
                                confirmButtonText: 'Copy',
                                heightAuto : false,
                            }).then((confirmError) => {
                                if (confirmError.isConfirmed) {
                                    if (navigator.clipboard && window.isSecureContext) {
                                        navigator.clipboard.writeText(result.code);
                                    } else {
                                        // Buat elemen <textarea> sementara
                                        const textarea = document.createElement("textarea");
                                        textarea.value = result.code;
    
                                        // Pastikan elemen tidak terlihat di halaman
                                        textarea.style.position = "absolute";
                                        textarea.style.left = "-9999px";
                                        document.body.appendChild(textarea);
    
                                        // Pilih teks dalam <textarea>
                                        textarea.select();
    
                                        try {
                                            // Salin teks ke clipboard
                                            const successful = document.execCommand("copy");
                                            if (successful) {
                                                console.log("Text copied to clipboard!");
                                            } else {
                                                console.log("Failed to copy text to clipboard.");
                                            }
                                        } catch (err) {
                                            console.error("Error in copying text: ", err);
                                        }
    
                                        // Hapus elemen <textarea> setelah menyalin
                                        document.body.removeChild(textarea);
                                    }
                                }
                            });
                        } else if (result.code) {
                            code = result.code;
                            self.lastError = '';
                            self.lastGeneratedScript = result.code;
                            // Insert Answer From AI
                            var cur_line_code = self.$editor.session.getLine(cur_pos.row);
                            var cur_line_code_trim = cur_line_code.trimStart();
                            if (code.includes(cur_line_code_trim)) {
                                code = code.replace(cur_line_code_trim, '');
                            }
                            self.$editor.session.insert({
                                row: cur_pos.row,
                                column: 0,
                            }, code);
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
                            new swal('Error', result.message, 'error');
                    }
                }); 
            }               
        }
    },

    _onClickGeneralScriptAI: function (ev) {
        return false;
        // Deprecated
        var self = this;
        if (self.$editor && self.analysis_id) {
            var comment_char = false;
            if (self.scriptEditorType == 'Python') {
                comment_char = '#';
            } else if (self.scriptEditorType == 'PostgreSQL') {
                comment_char = '--';
            } else if (self.scriptEditorType == 'Javascript') {
                comment_char = '//';
            }
            var cur_pos = self.$editor.getCursorPosition();
            var row = cur_pos.row;
            var col = cur_pos.column;
            var spaces = '';
            for (var i = 0; i < col; i++) {
                spaces += ' ';
            }
            var comment_string = ''
            row = row - 1;
            while (row >= 0) {
                var line = self.$editor.session.getLine(row);
                var line_string = line.split(comment_char)
                if (line_string.length > 1) {
                    if (comment_string != '')
                        comment_string = line_string[1].trim() + '\n' + comment_string;
                    else
                        comment_string = line_string[1].trim();
                } else {
                    // Not Found Comment Char Anymore
                    break;
                }
                row--;
            }
            if (comment_string == '' && cur_pos.row > 0) {
                comment_string = self.$editor.session.getLine(cur_pos.row - 1).trim();
            }
            // Instruction to AI
            var instruction = `${comment_string}`
            jsonrpc('/web/dataset/call_kw/izi.analysis/action_get_lab_script', {
                model: 'izi.analysis',
                method: 'action_get_lab_script',
                args: [self.analysis_id, instruction],
                kwargs: {},
            }).then(function (result) {
                if (result.status == 200) {
                    // Insert Answer From AI
                    var code = result.code;
                    var codes = code.split('\n');
                    var spaced_codes = [];
                    codes.forEach(ans => {
                        spaced_codes.push(spaces + ans);
                    });
                    code = spaced_codes.join('\n') + '\n';
                    self.$editor.session.insert({
                        row: cur_pos.row,
                        column: 0,
                    }, code);
                    
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
                        new swal('Error', result.message, 'error');
                }
            });
        }
    },

    _onClickToggleFloatScript: function () {
        var self = this;
        if (self.$editorContainer) {
            if (!self.floatingScriptEditor) {
                self.$editorContainer.addClass('floating');
                self.$editorContainer.css('top', '30px');
                self.$editorContainer.css('bottom', '30px');
                self.$editorContainer.css('left', '10px');
                self.$editorContainer.css('right', '10px');
                self.$editorContainer.css('width', 'auto');
                self.$editorContainer.css('height', 'auto');
                self.$editor.resize();
                self.floatingScriptEditor = true;
                self.$visual._renderVisual();
            } else {
                self.$editorContainer.removeClass('floating');
                self.$editorContainer.css('top', 'auto');
                self.$editorContainer.css('bottom', 'auto');
                self.$editorContainer.css('left', 'auto');
                self.$editorContainer.css('right', 'auto');
                self.$editor.resize();
                self.floatingScriptEditor = false;
                self.$visual._renderVisual();
            }
        }
    },

    _onClickUpdateScript: function (ev, to_execute=true, callback=false) {
        var self = this;
        var script_css = ""
        if(self.scriptType == 'visual'){
            script_css = self.$editorCss.getValue();
        }
        var script = self.$editor.getValue();
        var analysis_id = self.analysis_id;
        var script_type = self.scriptType;

        new swal({
            title: "Update Script",
            text: `
                Do you confirm to update ${script_type} script for this analysis ?
            `,
            icon: "warning",
            showCancelButton: true,
            confirmButtonText: 'Yes',
            heightAuto : false,
        }).then((result) => {
            if (result.isConfirmed && script_type) {
                if (script_type == 'visual') {
                    jsonrpc('/web/dataset/call_kw/izi.analysis/write', {
                        model: 'izi.analysis',
                        method: 'write',
                        args: [[analysis_id], {render_visual_script: script,render_visual_script_css: script_css, use_render_visual_script: true}],
                        kwargs: {},
                    }).then(function (res) {
                        // console.log('Update Script', res);
                        if (self.parent && self.parent.$configAnalysis) {
                            self.parent.$configAnalysis._loadAnalysisInfo();
                            self.parent.$configAnalysis._renderVisual();
                        }
                        self.lastScript = script;
                        if (callback) {
                            callback();
                        } else {
                            self._onClickCloseScript();
                        }
                    });
                } else if (script_type == 'data') {
                    $('.spinner-container').addClass('d-flex');
                    jsonrpc('/web/dataset/call_kw/izi.analysis/try_write_data_script', {
                        model: 'izi.analysis',
                        method: 'try_write_data_script',
                        args: [[analysis_id], script, to_execute, self.context],
                        kwargs: {},
                    }).then(function (res) {
                        $('.spinner-container').removeClass('d-flex');
                        if (res && res.code == 200) {
                            // console.log('Update Script', res);
                            if (self.parent && self.parent.$configAnalysis) {
                                self.parent.$configAnalysis._loadAnalysisInfo();
                                self.parent.$configAnalysis._renderVisual();
                            }
                            self.lastScript = script;
                            self.lastGeneratedScript = script;
                            self.lastError = '';
                            if (callback) {
                                callback();
                            } else {
                                self._onClickCloseScript();
                            }
                        } else if (res.error) {
                            self.lastGeneratedScript = script;
                            self.lastError = res.error;
                            // new swal('Warning', res.error, 'warning');
                            new swal({
                                title: "Error!",
                                html: `<pre>${res.error}</pre><br/>Do you want to check the error with AI ?`,
                                icon: "warning",
                                showCancelButton: true,
                                confirmButtonText: 'Yes',
                                heightAuto : false,
                            }).then((confirmError) => {
                                if (confirmError.isConfirmed) {
                                    self._onClickContinueScriptAI(ev, self.lastGeneratedScript, self.lastError);
                                }
                            });
                        }
                    });
                }
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

export default IZIViewAnalysis;