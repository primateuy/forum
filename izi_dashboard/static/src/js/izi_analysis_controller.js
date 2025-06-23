/** @odoo-module */

import IZIViewAnalysis from "@izi_dashboard/js/component/main/izi_view_analysis";
import IZIConfigAnalysis from "@izi_dashboard/js/component/main/izi_config_analysis";
import { useService } from "@web/core/utils/hooks";
const { Component, useRef, onRendered, onPatched, onMounted } = owl;
export class IZIAnalysisController extends Component {
    setup(){
        self = this;
        self.action = useService('action');
        self.container = useRef('IZIAnalysisContainer');
        self.context = false;
        if (self.props && self.props.context) {
            self.context = self.props.context;
        };
        // self.render();
        onPatched(() => {
            self = this;
        });
        onMounted(() => {
            self = this;
            self.$el = $(self.container.el);
            console.log('onMounted', self.props.value);
            var $viewAnalysis = new IZIViewAnalysis(self);
            var $configAnalysis = new IZIConfigAnalysis(self, $viewAnalysis);
            $configAnalysis.appendTo(self.$el);
            $viewAnalysis.appendTo(self.$el);
            self.$viewAnalysis = $viewAnalysis;
            self.$configAnalysis = $configAnalysis;
        });
    }

    
}

IZIAnalysisController.template = "IZIAnalysis";