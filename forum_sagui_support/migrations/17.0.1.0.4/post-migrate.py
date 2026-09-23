# -*- coding: utf-8 -*-
# Los marcadores de dedup pasan de uno por mensaje a uno solo.
#
# Antes: un `ir.config_parameter` llamado `forum_sagui_support.publicado.<seq>` por cada respuesta
# entregada, y nada los borraba. Ahora: `forum_sagui_support.publicado_hasta`, un número.
#
# El orden importa y es el único detalle delicado de esta migración: primero se SIEMBRA la marca
# nueva con el máximo de los viejos, y sólo después se borran. Al revés —borrar y dejar que la marca
# se construya sola— deja la marca en cero por un rato, y en ese rato cualquier cola que Sagui
# reenvíe se republica: el usuario ve dos veces respuestas que ya leyó. Con la siembra primero, el
# peor caso es suprimir de más, que es el lado correcto del error.
import logging

_logger = logging.getLogger(__name__)

CLAVE = "forum_sagui_support.publicado_hasta"
PREFIJO = "forum_sagui_support.publicado."


def migrate(cr, version):
    cr.execute("""
        SELECT key FROM ir_config_parameter WHERE key LIKE %s AND key <> %s
    """, (PREFIJO + "%", CLAVE))
    viejos = [fila[0] for fila in cr.fetchall()]
    if not viejos:
        _logger.info("Sagui soporte: no había marcadores por mensaje que migrar")
        return

    seqs = []
    for clave in viejos:
        cola = clave[len(PREFIJO):]
        if cola.isdigit():
            seqs.append(int(cola))
    maximo = max(seqs) if seqs else 0

    # La marca nueva nunca baja: si ya existe con un valor más alto, manda ese.
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", (CLAVE,))
    fila = cr.fetchone()
    actual = int(fila[0]) if fila and (fila[0] or "").isdigit() else 0
    nuevo = max(actual, maximo)

    if fila:
        cr.execute("UPDATE ir_config_parameter SET value = %s WHERE key = %s", (str(nuevo), CLAVE))
    else:
        cr.execute("""
            INSERT INTO ir_config_parameter (key, value, create_uid, write_uid,
                                             create_date, write_date)
            VALUES (%s, %s, 1, 1, now(), now())
        """, (CLAVE, str(nuevo)))

    cr.execute("DELETE FROM ir_config_parameter WHERE key LIKE %s AND key <> %s",
               (PREFIJO + "%", CLAVE))
    _logger.info(
        "Sagui soporte: %s marcadores por mensaje colapsados en %s = %s (borrados %s)",
        len(viejos), CLAVE, nuevo, cr.rowcount)
