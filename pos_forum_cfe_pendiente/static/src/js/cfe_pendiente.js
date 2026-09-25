/** @odoo-module */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { PosStore } from "@point_of_sale/app/store/pos_store";

/**
 * Pantalla de emisión pendiente.
 *
 * Es deliberadamente un callejón sin salida: no tiene volver, no tiene cancelar
 * y mientras está arriba se oculta la barra superior (ver la herencia de
 * point_of_sale.Chrome en el XML). La única salida es que el CFE se emita.
 * La venta ya está cobrada y guardada; dejar seguir vendiendo sobre esa caja
 * escondería el problema hasta el cierre.
 */
export class CfePendienteScreen extends Component {
    static template = "pos_forum_cfe_pendiente.CfePendienteScreen";
    static props = {};

    setup() {
        this.pos = usePos();
        this.orm = useService("orm");
        this.state = useState({
            reintentando: false,
            error: this.pos.cfeEmisionPendiente?.cfe_emision_error || "",
            intentos: 0,
        });
    }

    get referencia() {
        return this.pos.cfeEmisionPendiente?.pos_reference || "";
    }

    async reintentar() {
        if (this.state.reintentando) {
            return;
        }
        this.state.reintentando = true;
        try {
            const res = await this.orm.call("pos.order", "reintentar_emision_cfe", [
                this.pos.cfeEmisionPendiente.id,
            ]);
            if (res.ok) {
                // Bloque: se completa lo que el flujo normal hace al terminar de
                // validar y que quedó sin hacer al cortar en push_single_order.
                const orden = this.pos.get_order();
                if (orden) {
                    this.pos.db.remove_unpaid_order(orden);
                }
                this.pos.cfeEmisionPendiente = null;
                this.pos.showScreen("ReceiptScreen");
                return;
            }
            this.state.error = res.error || _t("No se pudo emitir el CFE.");
            this.state.intentos = res.intentos || this.state.intentos;
        } catch (error) {
            // Que el reintento falle no puede romper la pantalla: se muestra el
            // motivo y se deja volver a intentar.
            this.state.error = error?.data?.message || error?.message || String(error);
        } finally {
            this.state.reintentando = false;
        }
    }
}

registry.category("pos_screens").add("CfePendienteScreen", CfePendienteScreen);

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        // Reactivo: el template del chrome lo mira para ocultar la barra.
        this.cfeEmisionPendiente = null;
    },

    /**
     * Corta el flujo de validación cuando el CFE no se pudo emitir.
     *
     * El servidor ya no falla en ese caso: guarda la venta, deja la factura en
     * borrador y devuelve la orden marcada. Devolver algo falso acá hace que
     * `_finalizeValidation` salga por su `if (!syncOrderResult) return;` —el
     * mismo en las tres implementaciones que conviven— y por lo tanto **no
     * avance a la pantalla de recibo**.
     */
    async push_single_order(order) {
        const res = await super.push_single_order(...arguments);
        const pendiente = Array.isArray(res)
            ? res.find((fila) => fila && fila.cfe_emision_pendiente)
            : null;
        if (pendiente) {
            this.cfeEmisionPendiente = pendiente;
            this.showScreen("CfePendienteScreen");
            return false;
        }
        return res;
    },
});
