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
 * EL INTERVALO SE APAGA SOLO. Mientras el estado no sea uno de ESTADOS_VIVOS
 * no hay ningún timer corriendo: en draft o done esta pantalla no hace un solo
 * request.
 *
 * SECCIONES POR FASE. Cada tipo de importación declara sus fases en
 * SECCIONES_POR_TIPO. Una fase es una barra con su cronómetro, su ETA, su ritmo
 * y sus contadores; el template las dibuja una debajo de la otra. Clientes
 * tiene una sola fase y se ve exactamente como antes.
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
const ESTADOS_VIVOS = ["processing", "loading", "applying"];
// Campos que se releen. Deliberadamente cortos: es lo que viaja cada 4 s.
const CAMPOS = [
    "state", "import_type", "offset", "total_rows", "processed", "created", "updated",
    "ignored", "errors", "cards_from_pool", "cards_created", "cards_updated",
    "quants_created", "quants_updated", "quants_zero",
    "current_phase", "apply_total", "apply_processed", "applied_count",
    "apply_no_diff", "apply_errors", "apply_started_at", "apply_ended_at",
    "started_at", "ended_at",
    "loading_step", "loading_steps_total", "loading_phase", "loading_started_at",
];
// Campos de fecha: el registro los entrega como luxon, el read como string.
const CAMPOS_FECHA = [
    "started_at", "ended_at", "loading_started_at", "apply_started_at", "apply_ended_at",
];
// Peso de la última muestra en el ritmo suavizado. Bajo = más estable.
const ALFA = 0.3;

/**
 * Fase única de clientes: arma el staging por etapas y después procesa filas.
 *
 * Cada constructor de fase recibe los datos (registro + polling) y devuelve:
 *   clave, titulo, corriendo, cargando, estadoFinal ('done'|'error'|'cancel'|null),
 *   hecho, total, inicio, fin, unidad, etapa, paso, pasos, filasContadores.
 */
function faseClientes(d) {
    const cargando = d.state === "loading";
    return {
        clave: "clientes",
        titulo: null,
        corriendo: ESTADOS_VIVOS.includes(d.state),
        cargando,
        estadoFinal: ["done", "error", "cancel"].includes(d.state) ? d.state : null,
        hecho: d.processed,
        total: d.total_rows,
        inicio: cargando ? d.loading_started_at : d.started_at,
        fin: d.ended_at,
        unidad: _t("filas/s"),
        etapa: d.loading_phase,
        paso: d.loading_step,
        pasos: d.loading_steps_total,
        filasContadores: [
            [
                { etiqueta: _t("Creados"), valor: d.created, clase: "text-success" },
                { etiqueta: _t("Actualizados"), valor: d.updated, clase: "" },
                { etiqueta: _t("Ignorados"), valor: d.ignored, clase: "text-muted" },
                { etiqueta: _t("Errores"), valor: d.errors, error: true },
            ],
            [
                { etiqueta: _t("Tarjetas del pool"), valor: d.cards_from_pool, clase: "" },
                { etiqueta: _t("Tarjetas creadas"), valor: d.cards_created, clase: "" },
                { etiqueta: _t("Tarjetas actualizadas"), valor: d.cards_updated, clase: "" },
            ],
        ],
    };
}

/**
 * Ajuste de inventario, fase 1: arma el staging desde el xlsx y carga el
 * conteo en los quants. Cuenta celdas, no filas del archivo.
 */
function faseCargaInventario(d) {
    const cargando = d.state === "loading";
    // Si ya se está aplicando (o se aplicó, o la aplicación se cortó), la
    // carga terminó bien: su error/cancelación sería de la otra fase.
    let estadoFinal = null;
    if (d.current_phase === "apply" || ["done", "applying", "applied"].includes(d.state)) {
        estadoFinal = "done";
    } else if (["error", "cancel"].includes(d.state)) {
        estadoFinal = d.state;
    }
    return {
        clave: "inventario_carga",
        titulo: _t("Fase 1 · Carga del conteo en los quants"),
        corriendo: ["loading", "processing"].includes(d.state),
        cargando,
        estadoFinal,
        hecho: d.processed,
        total: d.total_rows,
        inicio: cargando ? d.loading_started_at : d.started_at,
        fin: d.ended_at,
        unidad: _t("celdas/s"),
        etapa: d.loading_phase,
        paso: d.loading_step,
        pasos: d.loading_steps_total,
        filasContadores: [
            [
                { etiqueta: _t("Quants creados"), valor: d.quants_created, clase: "text-success" },
                { etiqueta: _t("Quants actualizados"), valor: d.quants_updated, clase: "" },
                { etiqueta: _t("En cero sin quant"), valor: d.quants_zero, clase: "text-muted" },
                { etiqueta: _t("Ignoradas"), valor: d.ignored, clase: "text-muted" },
                { etiqueta: _t("Errores"), valor: d.errors, error: true },
            ],
        ],
    };
}

/**
 * Ajuste de inventario, fase 2: aplica el ajuste por tandas (movimientos,
 * valuación y asientos). Aparece recién cuando se arrancó la aplicación.
 */
function faseAplicacionInventario(d) {
    const enAplicacion = d.current_phase === "apply";
    let estadoFinal = null;
    if (d.state === "applied") {
        estadoFinal = "done";
    } else if (enAplicacion && ["error", "cancel"].includes(d.state)) {
        estadoFinal = d.state;
    }
    return {
        clave: "inventario_aplicacion",
        titulo: _t("Fase 2 · Aplicación del ajuste"),
        corriendo: d.state === "applying",
        cargando: false,
        estadoFinal,
        hecho: d.apply_processed,
        total: d.apply_total,
        inicio: d.apply_started_at,
        fin: d.apply_ended_at,
        unidad: _t("celdas/s"),
        filasContadores: [
            [
                { etiqueta: _t("Quants ajustados"), valor: d.applied_count, clase: "text-success" },
                { etiqueta: _t("Sin diferencia"), valor: d.apply_no_diff, clase: "text-muted" },
                { etiqueta: _t("Errores"), valor: d.apply_errors, error: true },
            ],
        ],
    };
}

export const SECCIONES_POR_TIPO = {
    clientes: (d) => [faseClientes(d)],
    inventario: (d) => {
        const fases = [faseCargaInventario(d)];
        if (d.current_phase === "apply" || ["applying", "applied"].includes(d.state)) {
            fases.push(faseAplicacionInventario(d));
        }
        return fases;
    },
};

export class ForumImportProgress extends Component {
    static template = "forum_partner_import.LiveProgress";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");

        this.state = useState({
            vivo: null,        // último payload del polling, o null
            ahora: Date.now(),
            ritmos: {},        // unidades por segundo, suavizado, por fase
        });

        this.timerPoll = null;
        this.timerReloj = null;
        this.ultimasMuestras = {};   // {clave: {hecho, t}} de la lectura anterior
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
            this.ultimasMuestras = {};
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
                this.ultimasMuestras = {};
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
            this.ultimasMuestras = {};
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
        this._actualizarRitmos(datos);
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
     * Ritmo real medido entre lecturas, suavizado, fase por fase.
     *
     * Se usa el ritmo reciente y no el promedio global (hecho / tiempo total)
     * porque el promedio global queda contaminado si el proceso estuvo pausado
     * o si se reanudó: daría un ETA pesimista que no se corresponde con lo que
     * está pasando ahora. Solo se mide la fase que está corriendo.
     *
     * Una lectura SIN avance no cuenta como muestra. El avance llega de a
     * saltos, con el commit de cada tanda: en la aplicación del ajuste una
     * tanda tarda más de un minuto, y medir cada 4 s daba ritmo 0 una y otra
     * vez, con un ETA que se iba a decenas de horas. Así el ritmo se mide de
     * salto a salto.
     */
    _actualizarRitmos(datos) {
        const ahora = Date.now();
        for (const fase of this._fases(Object.assign({}, this._base(), datos))) {
            if (!fase.corriendo || fase.cargando) {
                continue;
            }
            const previa = this.ultimasMuestras[fase.clave];
            if (!previa) {
                this.ultimasMuestras[fase.clave] = { hecho: fase.hecho, t: ahora };
                continue;
            }
            const dt = (ahora - previa.t) / 1000;
            const dn = fase.hecho - previa.hecho;
            if (dn === 0) {
                continue;   // sin avance: se mide en el próximo salto, desde la misma muestra
            }
            this.ultimasMuestras[fase.clave] = { hecho: fase.hecho, t: ahora };
            if (dt <= 0 || dn < 0) {
                continue;
            }
            const instantaneo = dn / dt;
            const anterior = this.state.ritmos[fase.clave];
            this.state.ritmos[fase.clave] = anterior
                ? ALFA * instantaneo + (1 - ALFA) * anterior
                : instantaneo;
        }
    }

    // --- lo que se pinta ---------------------------------------------------

    /** Valores del registro, con los enteros en 0 y las fechas tal cual. */
    _base() {
        const d = this.props.record.data;
        const base = {};
        for (const campo of CAMPOS) {
            base[campo] = CAMPOS_FECHA.includes(campo) || typeof d[campo] === "string"
                ? d[campo]
                : d[campo] || 0;
        }
        return base;
    }

    get datos() {
        // El registro es la base; lo del polling se superpone.
        const base = this._base();
        return this.state.vivo ? Object.assign({}, base, this.state.vivo) : base;
    }

    _fases(d) {
        const constructor = SECCIONES_POR_TIPO[d.import_type] || SECCIONES_POR_TIPO.clientes;
        return constructor(d);
    }

    /** Fases listas para el template, con lo derivado ya calculado. */
    get secciones() {
        return this._fases(this.datos).map((fase) => this._decorar(fase));
    }

    get corriendo() {
        return ESTADOS_VIVOS.includes(this.datos.state);
    }

    _decorar(fase) {
        const hayErrores = fase.filasContadores
            .flat()
            .some((c) => c.error && (c.valor || 0) > 0);
        const segundos = this._segundos(fase);
        return Object.assign({}, fase, {
            porcentaje: this._porcentaje(fase),
            detalleBarra: this._detalleBarra(fase),
            hayErrores,
            transcurrido: segundos === null ? "—" : this._hhmmss(segundos),
            eta: this._eta(fase, segundos),
            ritmoTexto: this._ritmoTexto(fase),
            filasContadores: fase.filasContadores.map((fila) =>
                fila.map((c) => Object.assign({}, c, {
                    texto: this.fmt(c.valor),
                    claseValor: c.error
                        ? ((c.valor || 0) > 0 ? "fs-5 fw-bold text-danger" : "fs-5 fw-bold text-muted")
                        : `fs-5 fw-bold ${c.clase || ""}`,
                    claseCaja: c.error && (c.valor || 0) > 0
                        ? "border rounded p-2 text-center border-danger"
                        : "border rounded p-2 text-center",
                }))
            ),
            claseColumna: (fila) => (fila.length === 4 ? "col-6 col-md-3"
                : fila.length === 3 ? "col-6 col-md-4" : "col-6 col-md"),
        });
    }

    _porcentaje(fase) {
        if (fase.cargando) {
            // Durante el armado no hay filas procesadas que contar: la barra
            // avanza por etapas terminadas.
            return fase.pasos
                ? Math.min(100, Math.round((fase.paso / fase.pasos) * 100))
                : 0;
        }
        return fase.total
            ? Math.min(100, Math.round((fase.hecho / fase.total) * 100))
            : 0;
    }

    /** Texto de la derecha de la barra: etapas mientras carga, filas al procesar. */
    _detalleBarra(fase) {
        if (fase.cargando) {
            return fase.pasos ? _t("etapa %s de %s", fase.paso, fase.pasos) : "";
        }
        return `${this.fmt(fase.hecho)} / ${this.fmt(fase.total)}`;
    }

    /** Segundos transcurridos desde que arrancó la fase (hasta el fin, si terminó). */
    _segundos(fase) {
        const inicio = this._aMilis(fase.inicio);
        if (!inicio) {
            return null;
        }
        const fin = this._aMilis(fase.fin) || this.state.ahora;
        return Math.max(0, Math.round((fin - inicio) / 1000));
    }

    /** Estimación de lo que falta, con el ritmo medido entre lecturas. */
    _eta(fase, segundos) {
        // Durante el armado del staging no hay ritmo por fila que proyectar:
        // mostrar un número inventado sería peor que no mostrar nada.
        if (!fase.corriendo || fase.cargando) {
            return null;
        }
        const faltan = fase.total - fase.hecho;
        if (faltan <= 0) {
            return _t("terminando…");
        }
        // Sin un salto medido todavía no se estima. El promedio global (hecho /
        // transcurrido) parecía un buen respaldo, pero incluye las pausas: al
        // reanudar una aplicación cortada durante horas daba ETAs de un día.
        const ritmo = this.state.ritmos[fase.clave];
        if (!ritmo || ritmo <= 0) {
            return _t("calculando…");
        }
        return this._hhmmss(Math.round(faltan / ritmo));
    }

    _ritmoTexto(fase) {
        const r = fase.cargando ? 0 : this.state.ritmos[fase.clave];
        if (!r) {
            return "";
        }
        return `${Math.round(r).toLocaleString()} ${fase.unidad}`;
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
