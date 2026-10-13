/** @odoo-module **/

/**
 * Avance en vivo de un proceso de reposición en segundo plano.
 *
 * Mismo criterio que el de forum_partner_import: polling liviano cada 4 s y sólo
 * mientras el proceso está vivo (en cola o procesando); se pinta desde
 * `props.record.data` con lo del polling superpuesto, y al terminar se recarga el
 * formulario una vez para que el resto (log, reglas, operaciones) quede al día.
 *
 * El avance llega de a saltos —un commit por sub-lote de 300 reglas—, así que el
 * ritmo se mide de salto a salto y no entre lecturas.
 */

import { Component, onWillUnmount, useEffect, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

const INTERVALO_POLL = 4000;
const INTERVALO_RELOJ = 1000;
const ESTADOS_VIVOS = ["cola", "procesando"];
const CAMPOS = [
    "state", "total", "procesadas", "repuestas", "sin_stock", "errores", "omitidas",
    "paso", "started_at", "ended_at", "estancado",
];
const CAMPOS_FECHA = ["started_at", "ended_at"];
const ALFA = 0.3;

export class ForumReposicionProgreso extends Component {
    static template = "forum_reorder_origin.ReposicionProgreso";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ vivo: null, ahora: Date.now(), ritmo: null });
        this.timerPoll = null;
        this.timerReloj = null;
        this.muestra = null;
        this.yaRecargo = false;
        this.idActual = null;
        this.leyoInicial = false;
        this.ultimoEstadoRegistro = null;

        useEffect(
            () => this._sincronizarTimers(),
            () => [
                this.props.record.data.state,
                this.state.vivo && this.state.vivo.state,
                this.props.record.resId,
            ]
        );
        onWillUnmount(() => this._pararTodo());
    }

    _pararTodo() {
        clearInterval(this.timerPoll);
        clearInterval(this.timerReloj);
        this.timerPoll = this.timerReloj = null;
    }

    _sincronizarTimers() {
        const id = this.props.record.resId;
        if (id !== this.idActual) {
            this.idActual = id;
            this.leyoInicial = false;
            this.muestra = null;
            this.yaRecargo = false;
            this.ultimoEstadoRegistro = null;
            this.state.vivo = null;
            this.state.ritmo = null;
        }
        const estadoRegistro = this.props.record.data.state;
        if (estadoRegistro !== this.ultimoEstadoRegistro) {
            this.ultimoEstadoRegistro = estadoRegistro;
            if (this.state.vivo && this.state.vivo.state !== estadoRegistro) {
                this.state.vivo = null;
                this.leyoInicial = false;
            }
        }
        if (id && !this.leyoInicial) {
            this.leyoInicial = true;
            this._consultar();
        }
        if (!ESTADOS_VIVOS.includes(this.datos.state)) {
            this._pararTodo();
            return;
        }
        if (this.timerPoll) {
            return;
        }
        this.yaRecargo = false;
        this.timerPoll = setInterval(() => this._consultar(), INTERVALO_POLL);
        this.timerReloj = setInterval(() => (this.state.ahora = Date.now()), INTERVALO_RELOJ);
    }

    async _consultar() {
        const id = this.props.record.resId;
        if (!id) {
            return;
        }
        let filas;
        try {
            filas = await this.orm.read(this.props.record.resModel, [id], CAMPOS);
        } catch {
            return; // se reintenta en el próximo tick
        }
        if (!filas || !filas.length) {
            return;
        }
        const datos = filas[0];
        this._medirRitmo(datos);
        this.state.vivo = datos;
        if (!ESTADOS_VIVOS.includes(datos.state)) {
            this._pararTodo();
            if (!this.yaRecargo) {
                this.yaRecargo = true;
                this.props.record.load();
            }
        }
    }

    _medirRitmo(datos) {
        const ahora = Date.now();
        if (!this.muestra) {
            this.muestra = { hecho: datos.procesadas, t: ahora };
            return;
        }
        const dn = datos.procesadas - this.muestra.hecho;
        if (dn === 0) {
            return;
        }
        const dt = (ahora - this.muestra.t) / 1000;
        this.muestra = { hecho: datos.procesadas, t: ahora };
        if (dt <= 0 || dn < 0) {
            return;
        }
        const instantaneo = dn / dt;
        this.state.ritmo = this.state.ritmo
            ? ALFA * instantaneo + (1 - ALFA) * this.state.ritmo
            : instantaneo;
    }

    get datos() {
        const d = this.props.record.data;
        const base = {};
        for (const campo of CAMPOS) {
            base[campo] = CAMPOS_FECHA.includes(campo) || typeof d[campo] !== "number"
                ? d[campo]
                : d[campo] || 0;
        }
        return this.state.vivo ? Object.assign({}, base, this.state.vivo) : base;
    }

    get vista() {
        const d = this.datos;
        const corriendo = ESTADOS_VIVOS.includes(d.state);
        const porcentaje = d.total ? Math.min(100, Math.round((100 * d.procesadas) / d.total)) : 0;
        const segundos = this._segundos(d);
        let eta = null;
        if (corriendo) {
            const faltan = d.total - d.procesadas;
            eta = faltan <= 0 ? _t("terminando…")
                : this.state.ritmo ? this._hhmmss(Math.round(faltan / this.state.ritmo))
                : _t("calculando…");
        }
        const hayProblemas = (d.sin_stock || 0) + (d.errores || 0) > 0;
        return {
            corriendo,
            enCola: d.state === "cola",
            estancado: corriendo && d.estancado,
            porcentaje,
            detalle: `${this.fmt(d.procesadas)} / ${this.fmt(d.total)}`,
            claseBarra: corriendo
                ? "progress-bar-striped progress-bar-animated bg-primary"
                : hayProblemas ? "bg-warning" : "bg-success",
            transcurrido: segundos === null ? "—" : this._hhmmss(segundos),
            eta,
            ritmo: corriendo && this.state.ritmo
                ? `${Math.round(this.state.ritmo * 60).toLocaleString()} ${_t("reglas/min")}` : "",
            paso: corriendo ? d.paso : null,
            contadores: [
                { etiqueta: _t("Repuestas"), valor: d.repuestas, clase: "text-success" },
                { etiqueta: _t("Sin stock en origen"), valor: d.sin_stock, alerta: true },
                { etiqueta: _t("Con error"), valor: d.errores, alerta: true },
                { etiqueta: _t("Omitidas"), valor: d.omitidas, clase: "text-muted" },
            ].map((c) => ({
                ...c,
                texto: this.fmt(c.valor),
                claseValor: c.alerta
                    ? (c.valor > 0 ? "fs-5 fw-bold text-danger" : "fs-5 fw-bold text-muted")
                    : `fs-5 fw-bold ${c.clase}`,
                claseCaja: c.alerta && c.valor > 0
                    ? "border rounded p-2 text-center border-danger"
                    : "border rounded p-2 text-center",
            })),
        };
    }

    _segundos(d) {
        const inicio = this._aMilis(d.started_at);
        if (!inicio) {
            return null;
        }
        const fin = this._aMilis(d.ended_at) || this.state.ahora;
        return Math.max(0, Math.round((fin - inicio) / 1000));
    }

    _aMilis(valor) {
        if (!valor) {
            return null;
        }
        if (typeof valor === "string") {
            return new Date(valor.replace(" ", "T") + "Z").getTime();
        }
        return valor.toMillis ? valor.toMillis() : null;
    }

    _hhmmss(total) {
        const dd = (n) => String(n).padStart(2, "0");
        return `${dd(Math.floor(total / 3600))}:${dd(Math.floor((total % 3600) / 60))}:${dd(total % 60)}`;
    }

    fmt(n) {
        return (n || 0).toLocaleString();
    }
}

registry.category("fields").add("forum_reposicion_progreso", {
    component: ForumReposicionProgreso,
    supportedTypes: ["float", "integer"],
});
