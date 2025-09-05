def _post_init_hook(env):
    """
    Establece todos las stock_picking_type con is_import_op = False;
    Establece todos las stock_picking con import_op_status = 'closed'
    """
    env.cr.execute(
        """
        UPDATE stock_picking_type
        SET
        is_import_op = False
        """
    )

    env.cr.execute(
        """
        UPDATE stock_picking
        SET
        import_op_status = 'closed'
        """
    )
    
    pickings = env['stock.picking'].search([])
    if len(pickings) > 0:
        pickings.write({'import_op_status': 'closed'})
