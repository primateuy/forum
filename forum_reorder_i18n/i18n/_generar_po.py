# -*- coding: utf-8 -*-
"""Genera i18n/es_UY.po tomando los bloques del export de Odoo.

Se reusan los comentarios "#:" del export tal cual: son los que le dicen al importador a
que registro aplicar cada traduccion. Escribirlos a mano es la forma mas facil de que una
traduccion se cargue "bien" y no aparezca en pantalla.

Uso:
    1. Exportar los terminos vigentes de la base a un .po (ver __manifest__.py).
    2. python3 _generar_po.py <ruta_del_export.po>
       Sin argumento busca /tmp/reorder_es_UY.po.

El resultado se escribe en es_UY.po, al lado de este script.
"""
import io, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fuente_traducciones import TRADUCCIONES

AQUI = os.path.dirname(os.path.abspath(__file__))
ORIGEN = sys.argv[1] if len(sys.argv) > 1 else '/tmp/reorder_es_UY.po'
DESTINO = os.path.join(AQUI, 'es_UY.po')

s = io.open(ORIGEN, encoding='utf-8').read()
bloques = s.split('\n\n')

def leer_msg(bloque, clave):
    """Devuelve el valor de msgid/msgstr, soportando continuaciones multilinea."""
    m = re.search(r'^%s ""\n((?:".*"\n?)+)' % clave, bloque, re.M)
    if m:
        return ''.join(re.findall(r'^"(.*)"$', m.group(1), re.M)), True
    m = re.search(r'^%s "(.*)"$' % clave, bloque, re.M)
    return (m.group(1) if m else None), False

def escapar(txt):
    return txt.replace('\\', '\\\\').replace('"', '\\"')

salida, usados, ya_ok = [], set(), 0
for b in bloques:
    if not b.strip() or b.lstrip().startswith('# Translation of Odoo'):
        continue
    msgid, _ = leer_msg(b, 'msgid')
    msgstr, _ = leer_msg(b, 'msgstr')
    if not msgid or msgid not in TRADUCCIONES:
        continue
    nueva = TRADUCCIONES[msgid]
    # Se incluye el bloque incluso si el msgstr exportado ya coincide: el export muestra un
    # solo valor por msgid, pero el bloque puede referenciar decenas de registros y algunos
    # de ellos siguen sin traducir. Dejarlo afuera los condena a quedar en ingles.
    if msgstr == nueva:
        ya_ok += 1
    refs = [l for l in b.split('\n')
            if l.startswith('#.') or l.startswith('#:') or l.startswith('#,')]
    salida.append('\n'.join(refs) + '\n'
                  + 'msgid "%s"\n' % escapar(msgid)
                  + 'msgstr "%s"\n' % escapar(nueva))
    usados.add(msgid)

cabecera = '''# Translation of Odoo Server.
# This file contains the translation of the following modules:
#\t* setu_advance_reordering
#\t* setu_intercompany_transaction
#\t* forum_reorder_origin
#\t* primate_reposicion_avanzada
#
# Mantenido por Primate en el modulo forum_reorder_i18n. Ver el __manifest__.py de ese
# modulo para el glosario de terminos y el procedimiento de actualizacion.
#
msgid ""
msgstr ""
"Project-Id-Version: Odoo Server 17.0\\n"
"Report-Msgid-Bugs-To: \\n"
"Last-Translator: Primate <https://primate.uy>\\n"
"Language-Team: \\n"
"Language: es_UY\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"

'''
io.open(DESTINO, 'w', encoding='utf-8').write(cabecera + '\n'.join(salida))

faltan = sorted(set(TRADUCCIONES) - usados)
print('bloques escritos      :', len(salida))
print('ya estaban correctos  :', ya_ok)
print('msgid no encontrados  :', len(faltan))
for f in faltan:
    print('   NO ENCONTRADO:', f)
