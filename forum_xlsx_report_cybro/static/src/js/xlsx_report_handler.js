/** @odoo-module **/

import { download } from "@web/core/network/download";
import { registry } from "@web/core/registry";

/**
 * Reportes XLSX de Cybrosys: report_type 'xlsx' sin report_name y con los datos
 * para su ruta /xlsx_reports en action.data (model, options, output_format, report_name).
 */
function esReporteCybrosys(action) {
    const data = action.data || {};
    return (
        action.report_type === "xlsx" &&
        !action.report_name &&
        data.output_format === "xlsx" &&
        Boolean(data.model)
    );
}

// Corre antes que el manejador de report_xlsx de OCA (sequence por defecto 50), que
// tomaría el pedido y fallaría buscando el modelo «report.undefined».
registry.category("ir.actions.report handlers").add(
    "forum_xlsx_report_cybro",
    async function (action, options, env) {
        if (!esReporteCybrosys(action)) {
            return false;
        }
        env.services.ui.block();
        try {
            await download({ url: "/xlsx_reports", data: action.data });
        } finally {
            env.services.ui.unblock();
        }
        if (options.onClose) {
            options.onClose();
        }
        return true;
    },
    { sequence: 1 }
);
