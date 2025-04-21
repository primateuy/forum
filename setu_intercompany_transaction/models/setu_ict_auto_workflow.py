from odoo import models, fields, api, _

class SetuICTAutoWorkflow(models.Model):
    _name = 'setu.ict.auto.workflow'
    _description = """
        This model is used to automate some activities in the intercompany transactions. 
        Like, Auto confirm sales order, purchase order, auto create customer invoice, vendor bill etc... 
    """
    name = fields.Char("Name")
    validate_ict = fields.Boolean("Validate intercompany record?", help="""
        If this option is selected then it will create intercompany sale / purchase automatically
    """)
    validate_ict_so_po = fields.Boolean("Validate intercompany sale / purchase?")
    create_ict_invoices = fields.Boolean("Create intercompany invoices?")
    validate_ict_invoices = fields.Boolean("Validate intercompany invoices?")
    ict_channel_ids = fields.One2many("setu.intercompany.channel", "auto_workflow_id", "ICT Channels")

    def execute_workflow(self):
        domain = [('state','=','draft'), ('auto_workflow_id','!=', False)]
        ict = self.env['setu.intercompany.transfer'].search(domain)
        if not self.auto_workflow_id:
            return

        if self.auto_workflow_id.validate_ict:
            ict.action_validate_intercompany_transfer()

        return True
