{
    "name": "Cambio de Precio POS (Safe)",
    "version": "17.0.1.0.0",
    "summary": "Extiende recompensas de POS sin interferir con loyalty estándar",
    "author": "Custom",
    "depends": ["point_of_sale", "pos_loyalty"],
    "assets": {
        "point_of_sale._assets_pos": [
            "cambio_precio/static/src/js/reward_patch.js"
        ]
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3"
}