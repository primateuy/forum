# -*- coding: utf-8 -*-
"""El cron pasa a quedar siempre activo.

Hasta la 17.0.1.0.0 el módulo intentaba prender y apagar su propio cron. Apagarlo
nunca funcionó: `ir.cron.write()` llama a `_try_lock()`, que pide un lock sobre
su propia fila, y esa fila ya está tomada por el cursor que ejecuta el job. El
resultado era un LockNotAvailable en cada tick con el cron sin nada que hacer.

El registro se creó con `noupdate=1`, así que el `ir_cron.xml` nuevo no lo
alcanza por más que ahora declare `noupdate="0"`. Acá se corrige el flag una vez
—para que de acá en más mande la definición del XML— y se aplican los valores
nuevos al registro existente.

Va por SQL directo a propósito: es lo mismo que hace el ORM para estos campos y
esquiva el `_try_lock` que es justamente el origen del problema.
"""


def migrate(cr, version):
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'forum_partner_import'
           AND name = 'ir_cron_forum_partner_import'
           AND model = 'ir.cron'
    """)
    fila = cr.fetchone()
    if not fila:
        return

    cr.execute("""
        UPDATE ir_model_data SET noupdate = false
         WHERE module = 'forum_partner_import'
           AND name = 'ir_cron_forum_partner_import'
    """)
    cr.execute("""
        UPDATE ir_cron
           SET active = true, interval_number = 10, interval_type = 'minutes'
         WHERE id = %s
    """, (fila[0],))
