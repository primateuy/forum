/** @odoo-module **/

/**
 * Avance en vivo de una importación masiva.
 *
 * POR QUÉ EXISTE. El formulario estándar muestra los valores que tenía el
 * registro cuando se cargó la página. Una importación de 646.000 filas tarda
 * minutos y avanza con el commit de cada tanda: sin esto, para saber si el
 * proceso avanza o murió hay que refrescar a mano.
 *
 * POLLING Y NO BUS. El bus obligaría a que el cron emita desde el servidor y a
 * manejar canales y reconexiones. Para una pantalla de administración, un read
 * liviano cada 4 segundos alcanza y tiene muchas menos piezas que se puedan
 * romper. El costo es un request cada 4 s mientras dure el proceso, y solo
 * mientras la pantalla está abierta.
 *
 * SE PINTA DESDE `props.record.data`, NO DESDE UNA COPIA. `setup()` corre una
 * sola vez, al montar: guardar ahí una copia del registro deja la pantalla
 * mostrando valores viejos cuando el registro se recarga. Lo que llega del
 * polling se superpone encima, y cuando no hay nada del polling se ve el
 * registro tal cual.
 *
 * EL INTERVALO SE APAGA SOLO. Mientras el estado no sea processing/loading no
 * hay ningún timer corriendo: en draft o done esta pantalla no hace un solo
 * request.
 */

import { Component, onWillUnmount, useEffect, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

// Cada cuánto se le pregunta al servidor por el avance.
const INTERVALO_POLL = 4000;
// El cronómetro corre aparte, más fino, porque no cuesta nada.
const INTERVALO_RELOJ = 1000;
// Estados en los que tiene sentido preguntar.
const ESTADOS_VIVOS = ["processing", "loading"];
// Campos que se releen. Deliberadamente cortos: es lo que viaja cada 4 s.
const CAMPOS = [
    "state", "offset", "total_rows", "processed", "created", "updated",
    "ignored", "errors", "cards_from_pool", "cards_created", "cards_updated",
    "started_at", "ended_at",
    "loading_step", "loading_steps_total", "loading_phase", "loading_started_at",
];
// Peso de la última muestra en el ritmo suavizado. Bajo = más estable.
const ALFA = 0.3;

export class ForumImportProgress extends Component {
    static template = "forum_partner_import.LiveProgress";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");

        this.state = useState({
            vivo: null,        // último payload del polling, o null
            ahora: Date.now(),
            ritmo: 0,          // filas por segundo, suavizado
        });

        this.timerPoll = null;
        this.timerReloj = null;
        this.ultimaMuestra = null;   // {procesadas, t} de la lectura anterior
        this.yaRecargo = false;
        this.idActual = null;
        this.leyoInicial = false;
        this.ultimoEstadoRegistro = null;

        // Se mira el VALOR del estado después de cada render y se prende o
        // apaga el polling en consecuencia. Con onWillUpdateProps no alcanza:
        // el record que llega por props es siempre el mismo objeto, así que el
        // hook puede no dispararse aunque los datos de adentro hayan cambiado.
        // Se miran los DOS estados: el del registro y el de la última lectura.
        // Si solo se mirara `datos.state`, en cuanto llega la primera lectura
        // el polling tapa al registro para siempre y un cambio hecho por un
        // botón (que recarga el registro) no se vería nunca.
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

    // --- timers ------------------------------------------------------------

    _pararTodo() {
        if (this.timerPoll) {
            clearInterval(this.timerPoll);
            this.timerPoll = null;
        }
        if (this.timerReloj) {
            clearInterval(this.timerReloj);
            this.timerReloj = null;
        }
    }

    _sincronizarTimers() {
        const id = this.props.record.resId;
        if (id !== this.idActual) {
            this.idActual = id;
            this.leyoInicial = false;
            this.ultimaMuestra = null;
            this.yaRecargo = false;
            this.ultimoEstadoRegistro = null;
            this.state.vivo = null;
        }

        // Si el registro cambió de estado es porque el formulario lo recargó
        // contra el servidor, y eso es más nuevo que la última lectura del
        // polling: se descarta lo viejo para que no lo siga tapando.
        const estadoRegistro = this.props.record.data.state;
        if (estadoRegistro !== this.ultimoEstadoRegistro) {
            this.ultimoEstadoRegistro = estadoRegistro;
            if (this.state.vivo && this.state.vivo.state !== estadoRegistro) {
                this.state.vivo = null;
                this.ultimaMuestra = null;
                this.leyoInicial = false;
            }
        }

        // Una lectura inicial contra el servidor, aunque el registro del
        // cliente diga que no está corriendo. Cubre el caso de abrir el
        // formulario sobre un batch que ya venía procesando: el registro pudo
        // haberse cargado de una caché anterior al arranque, y sin esto la
        // pantalla se quedaría quieta hasta que alguien refresque.
        // Es UNA lectura, no un timer: en draft o done no queda nada corriendo.
        if (id && !this.leyoInicial) {
            this.leyoInicial = true;
            this._consultar();
        }

        const corriendo = ESTADOS_VIVOS.includes(this.datos.state);

        if (!corriendo) {
            this._pararTodo();
            this.ultimaMuestra = null;
            return;
        }
        if (this.timerPoll) {
            return;   // ya estaba andando
        }
        this.yaRecargo = false;
        this.timerPoll = setInterval(() => this._consultar(), INTERVALO_POLL);
        this.timerReloj = setInterval(() => {
            this.state.ahora = Date.now();
        }, INTERVALO_RELOJ);
        this._consultar();   // una primera lectura sin esperar los 4 s
    }

    async _consultar() {
        const id = this.props.record.resId;
        if (!id) {
            return;
        }
        let filas;
        try {
            filas = await this.orm.read("forum.import.batch", [id], CAMPOS);
        } catch {
            // Un error de red no debe dejar la pantalla rota: se reintenta en
            // el próximo tick y mientras tanto se sigue viendo lo último bueno.
            return;
        }
        if (!filas || !filas.length) {
            return;
        }
        const datos = filas[0];
        this._actualizarRitmo(datos.processed);
        this.state.vivo = datos;

        if (!ESTADOS_VIVOS.includes(datos.state)) {
            // Terminó: se apagan los timers y se recarga el formulario una sola
            // vez, para que el resto de la pantalla (log, fechas) quede al día.
            this._pararTodo();
            if (!this.yaRecargo) {
                this.yaRecargo = true;
                this.props.record.load();
            }
        }
    }

    /**
     * Ritmo real medido entre lecturas, suavizado.
     *
     * Se usa el ritmo reciente y no el promedio global (procesadas / tiempo
     * total) porque el promedio global queda contaminado si el proceso estuvo
     * pausado o si se reanudó: daría un ETA pesimista que no se corresponde
     * con lo que está pasando ahora.
     */
    _actualizarRitmo(procesadas) {
        const ahora = Date.now();
        const previa = this.ultimaMuestra;
        this.ultimaMuestra = { procesadas, t: ahora };
        if (!previa) {
            return;
        }
        const dt = (ahora - previa.t) / 1000;
        const dn = procesadas - previa.procesadas;
        if (dt <= 0 || dn < 0) {
            return;
        }
        const instantaneo = dn / dt;
        this.state.ritmo = this.state.ritmo
            ? ALFA * instantaneo + (1 - ALFA) * this.state.ritmo
            : instantaneo;
    }

    // --- lo que se pinta ---------------------------------------------------

    get datos() {
        // El registro es la base; lo del polling se superpone.
        const d = this.props.record.data;
        const base = {
            state: d.state,
            offset: d.offset || 0,
            total_rows: d.total_rows || 0,
            processed: d.processed || 0,
            created: d.created || 0,
            updated: d.updated || 0,
            ignored: d.ignored || 0,
            errors: d.errors || 0,
            cards_from_pool: d.cards_from_pool || 0,
            cards_created: d.cards_created || 0,
            cards_updated: d.cards_updated || 0,
            started_at: d.started_at,
            ended_at: d.ended_at,
            loading_step: d.loading_step || 0,
            loading_steps_total: d.loading_steps_total || 0,
            loading_phase: d.loading_phase || "",
            loading_started_at: d.loading_started_at,
        };
        return this.state.vivo ? Object.assign({}, base, this.state.vivo) : base;
    }

    get corriendo() {
        return ESTADOS_VIVOS.includes(this.datos.state);
    }

    /** Armando el staging: la barra va por etapas, no por filas. */
    get cargando() {
        return this.datos.state === "loading";
    }

    get termino() {
        return ["done", "error", "cancel"].includes(this.datos.state);
    }

    get porcentaje() {
        const d = this.datos;
        if (this.cargando) {
            // Durante el armado no hay filas procesadas que contar: la barra
            // avanza por etapas terminadas.
            return d.loading_steps_total
                ? Math.min(100, Math.round((d.loading_step / d.loading_steps_total) * 100))
                : 0;
        }
        return d.total_rows
            ? Math.min(100, Math.round((d.processed / d.total_rows) * 100))
            : 0;
    }

    /** Texto de la derecha de la barra: etapas mientras carga, filas al procesar. */
    get detalleBarra() {
        const d = this.datos;
        if (this.cargando) {
            return d.loading_steps_total
                ? _t("etapa %s de %s", d.loading_step, d.loading_steps_total)
                : "";
        }
        return `${this.fmt(d.processed)} / ${this.fmt(d.total_rows)}`;
    }

    get hayErrores() {
        return (this.datos.errors || 0) > 0;
    }

    /** Segundos transcurridos desde que arrancó (hasta el fin, si terminó). */
    get segundosTranscurridos() {
        const inicio = this._aMilis(
            this.cargando ? this.datos.loading_started_at : this.datos.started_at);
        if (!inicio) {
            return null;
        }
        const fin = this._aMilis(this.datos.ended_at) || this.state.ahora;
        return Math.max(0, Math.round((fin - inicio) / 1000));
    }

    get transcurrido() {
        const s = this.segundosTranscurridos;
        return s === null ? "—" : this._hhmmss(s);
    }

    /** Estimación de lo que falta, con el ritmo medido entre lecturas. */
    get eta() {
        // Durante el armado del staging no hay ritmo por fila que proyectar:
        // mostrar un número inventado sería peor que no mostrar nada.
        if (!this.corriendo || this.cargando) {
            return null;
        }
        const { processed, total_rows } = this.datos;
        const faltan = total_rows - processed;
        if (faltan <= 0) {
            return _t("terminando…");
        }
        let ritmo = this.state.ritmo;
        if (!ritmo) {
            // Todavía no hay dos lecturas: se cae al promedio global.
            const s = this.segundosTranscurridos;
            if (!s || !processed) {
                return _t("calculando…");
            }
            ritmo = processed / s;
        }
        if (ritmo <= 0) {
            return _t("calculando…");
        }
        return this._hhmmss(Math.round(faltan / ritmo));
    }

    get ritmoTexto() {
        const r = this.cargando ? 0 : this.state.ritmo;
        if (!r) {
            return "";
        }
        return _t("%s filas/s", Math.round(r).toLocaleString());
    }

    // --- helpers -----------------------------------------------------------

    _aMilis(valor) {
        if (!valor) {
            return null;
        }
        // El registro entrega luxon DateTime; el read del ORM, un string UTC.
        if (typeof valor === "string") {
            return new Date(valor.replace(" ", "T") + "Z").getTime();
        }
        return valor.toMillis ? valor.toMillis() : null;
    }

    _hhmmss(total) {
        const h = Math.floor(total / 3600);
        const m = Math.floor((total % 3600) / 60);
        const s = total % 60;
        const dd = (n) => String(n).padStart(2, "0");
        return `${dd(h)}:${dd(m)}:${dd(s)}`;
    }

    fmt(n) {
        return (n || 0).toLocaleString();
    }
}

export const forumImportProgressField = {
    component: ForumImportProgress,
    supportedTypes: ["float", "integer"],
};

registry.category("fields").add("forum_import_progress", forumImportProgressField);
