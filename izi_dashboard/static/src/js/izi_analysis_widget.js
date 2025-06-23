/** @odoo-module **/

import { registry } from "@web/core/registry";
import IZIViewVisual from "@izi_dashboard/js/component/main/izi_view_visual";
const { Component, useRef, onRendered, onPatched, onMounted } = owl;
class IZIAnalysisWidget extends Component {
    setup(){
        self = this;
        self.widgetContainer = useRef('widgetContainer');
        // self.render();
        onPatched(() => {
            self = this;
            console.log('onPatched', self.props.record.data);
            self.analysis_data = self.props.record.data[self.props.name];
            if (self.widgetContainer && self.widgetContainer.el && self.analysis_data) {
                var $el = $(self.widgetContainer.el);
                $el.empty();
                self.$visual = new IZIViewVisual(self, {
                    analysis_data: JSON.parse(self.analysis_data),
                });
                self.$visual.appendTo($el);
            }
        });
        onMounted(() => {
            self = this;
            console.log('onRendered', self.props.record.data);
            self.analysis_data = self.props.record.data[self.props.name];
            if (self.widgetContainer && self.widgetContainer.el && self.analysis_data) {
                var $el = $(self.widgetContainer.el);
                $el.empty();
                self.$visual = new IZIViewVisual(self, {
                    analysis_data: JSON.parse(self.analysis_data),
                });
                self.$visual.appendTo($el);
            }
        });
    }
}
IZIAnalysisWidget.template = 'izi_dashboard.IZIAnalysisWidget';

export const IZIAnalysisField = {
    component: IZIAnalysisWidget,
    supportedTypes: ["text"],
};
registry.category("fields").add("izi_analysis", IZIAnalysisField);