/** @odoo-module */

import { registry } from "@web/core/registry";
import { IZIDashboardController } from "@izi_dashboard/js/izi_dashboard_controller";

export const IZIDashboardView = {
    type: "izidashboard",
    display_name: "IZIDashboard",
    icon: "fa-tachometer",
    multiRecord: true,
    Controller: IZIDashboardController,
};

registry.category("views").add("izidashboard", IZIDashboardView);