from odoo import fields, models, api, _


class AdvanceReorderProcessAutoWorkflow(models.Model):
    _name = 'advance.reorder.process.auto.workflow'

    name = fields.Char("Name")
    validate = fields.Boolean("Validate Reorder")
    verify = fields.Boolean("Verify Reorder")
    create_po = fields.Boolean("Create Purchase Order")

    create_replenishment = fields.Boolean("Create Replenishment")
    validate_replenishment = fields.Boolean("Validate Replenishment")
    verify_replenishment = fields.Boolean("Verify Replenishment")

    @api.onchange('validate', 'verify', 'create_po', 'create_replenishment', 'validate_replenishment')
    def on_changes_workflow(self):
        vals = {}
        if not self.validate:
            vals.update({'verify': False,
                         'create_po': False,
                         'create_replenishment': False,
                         'validate_replenishment': False,
                         'verify_replenishment': False
                         })
        if not self.verify:
            vals.update({'create_po': False,
                         'create_replenishment': False,
                         'validate_replenishment': False,
                         'verify_replenishment': False
                         })
        if not self.create_po:
            vals.update({'create_replenishment': False,
                         'validate_replenishment': False,
                         'verify_replenishment': False
                         })
        if not self.create_replenishment:
            vals.update({'validate_replenishment': False,
                         'verify_replenishment': False
                         })
        return {'value': vals}
