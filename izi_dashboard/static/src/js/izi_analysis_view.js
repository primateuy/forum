/** @odoo-module */

import { registry } from "@web/core/registry";
import { IZIAnalysisController } from "@izi_dashboard/js/izi_analysis_controller";

export const IZIAnalysisView = {
    type: "izianalysis",
    display_name: "IZIAnalysis",
    icon: "fa-tachometer",
    multiRecord: true,
    Controller: IZIAnalysisController,
};

registry.category("views").add("izianalysis", IZIAnalysisView);