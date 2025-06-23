/** @odoo-module */

import IZIViewDashboard from "@izi_dashboard/js/component/main/izi_view_dashboard";
import IZIConfigDashboard from "@izi_dashboard/js/component/main/izi_config_dashboard";
import { useService } from "@web/core/utils/hooks";
const { Component, useRef, onRendered, onPatched, onMounted } = owl;
export class IZIDashboardController extends Component {
    setup(){
        self = this;
        self.action = useService('action');
        self.container = useRef('IZIDashboardContainer');
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
            var $viewDashboard = new IZIViewDashboard(self);
            var $configDashboard = new IZIConfigDashboard(self, $viewDashboard);
            $configDashboard.appendTo(self.$el);
            $viewDashboard.appendTo(self.$el);
            self.$viewDashboard = $viewDashboard;
            self.$configDashboard = $configDashboard;
        });
    }

    
}

IZIDashboardController.template = "IZIDashboard";