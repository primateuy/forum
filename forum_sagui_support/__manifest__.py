# -*- coding: utf-8 -*-
{
    'name': 'Forum — Agente de Soporte Sagui',
    'version': '17.0.1.0.5',
    'category': 'Productivity/Discuss',
    'summary': 'Puente entre el chat de Forum (Discuss y livechat) y el agente de soporte de Sagui',
    'description': """
Puente de soporte hacia Sagui
=============================

Este módulo NO tiene lógica de inteligencia artificial ni una copia de la documentación. Relaya.

Dos entradas, un solo núcleo:

* **DM de Discuss** — a Sagui se le escribe como a cualquier compañero. El usuario bot existe en
  Forum como un contacto más; el DM se siembra al instalar, igual que hace OdooBot, porque un
  usuario archivado no aparece en la búsqueda de «Nuevo mensaje».
* **Livechat del sitio** — un `chatbot.script` con un paso de entrada libre. Se usa el chatbot y
  no un operador-bot por una razón concreta: `_process_step_forward_operator` da el pase a un
  humano de forma nativa, que es justo lo que hace falta cuando Sagui deriva.

Lo que sale de Sagui para el usuario vuelve por la cola de salida, que este módulo sondea. La
respuesta del agente es síncrona; la del responsable humano llega cuando llega.

Si Sagui no responde, el usuario igual recibe un mensaje y queda una actividad local para el
responsable configurado acá. Nunca silencio.
""",
    'author': 'PrimateUY',
    'website': 'https://primate.uy',
    'license': 'LGPL-3',
    'depends': [
        'mail',
        'im_livechat',
    ],
    'data': [
        'data/sagui_bot_data.xml',
        'data/chatbot_script_data.xml',
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'post_init_hook': 'post_init_sembrar_dm',
}
