# -*- coding: utf-8 -*-
{
    'name': 'FORUM - Traducción Reposición Avanzada',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Traducción al español de los módulos de reordenamiento y transacciones '
               'inter-compañía / inter-almacén',
    'description': """
        Módulo que solo aporta traducciones. No tiene modelos, vistas ni lógica.

        Por qué existe:
        setu_advance_reordering y setu_intercompany_transaction son módulos de pago de Setu
        Consulting y no traen carpeta i18n. El resultado en pantalla es una mezcla:
        setu_intercompany_transaction está entero en inglés (137 campos), y lo que sí
        aparece en español viene de traducción automática, con errores y términos
        inconsistentes ("Canal de intermediación" por Inter Company Channel,
        "Flujo automático - TIC" por Auto Workflow - ICT, "Reordenamiento anticipado" en un
        menú y "avanzado" en otro). Para un usuario que no conoce el sistema eso desorienta
        más que el inglés.

        Va en un módulo aparte y no como i18n/ dentro de los módulos de Setu por dos razones:
        no se toca código del vendor, y una actualización del vendor no se lleva puestas las
        traducciones. Los .po de Odoo se aplican al registro que referencia cada entrada, no
        al módulo que envía el archivo, así que desde acá se traducen términos de cualquier
        módulo.

        Cómo actualizarlo:
        1. Exportar los términos vigentes con odoo-bin --i18n-export, pasando
        --language=es_UY y --modules con los cuatro módulos de arriba.
        2. Completar los msgstr vacíos en i18n/es_UY.po, conservando los comentarios "#:".
        Sin esos comentarios el importador no sabe a qué registro aplicar la traducción.
        3. Cargar con odoo-bin -u forum_reorder_i18n --i18n-overwrite. El --i18n-overwrite
        es imprescindible: sin él Odoo respeta las traducciones que ya existen y las
        correcciones de términos mal traducidos no se aplican.

        Lo que este módulo NO puede traducir:
        Los mensajes de error escritos con _() dentro del Python de Setu (entradas de tipo
        "code:" en el .po). Odoo resuelve esas llamadas contra el catálogo del módulo dueño
        del archivo, no contra el que envía el .po, así que la única forma de traducirlas es
        poner un i18n/ dentro del módulo del vendor — que es justamente lo que se evita acá.
        Son alrededor de diez mensajes de validación (por ejemplo "Please add any product to
        do a transfer."). Quedan en inglés a propósito: son avisos de error puntuales, no
        etiquetas de pantalla, y el costo de tocar el vendor es mayor que el beneficio.

        Glosario que se respeta en todo el módulo:
        Inter Company / Intercompany  -> Inter-Compañía
        Inter Warehouse               -> Inter-Almacén
        ICT / IWT                     -> se dejan como siglas, son las que usa el cliente
        Requestor                     -> Solicitante
        Fulfiller                     -> Abastecedor
        Replenishment                 -> Reposición
        Reordering                    -> Reordenamiento
    """,
    'author': 'Primate',
    'website': 'https://primateuy.odoo.com',
    'depends': [
        'setu_advance_reordering',
        'setu_intercompany_transaction',
        'forum_reorder_origin',
        'primate_reposicion_avanzada',
    ],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': True,
    'license': 'LGPL-3',
}
