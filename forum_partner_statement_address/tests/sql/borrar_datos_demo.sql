-- Borra los datos demo de la PoC de estado de cuenta por direccion.
-- Todos los registros sembrados llevan el prefijo 'POC-DIR' o el diario POCDI.
-- Revisar el SELECT de control antes de descomentar los DELETE.

-- Control: que se va a borrar
SELECT 'asientos' AS que, count(*) FROM account_move
 WHERE journal_id IN (SELECT id FROM account_journal WHERE code IN ('POCDI'))
UNION ALL
SELECT 'pagos', count(*) FROM account_payment p JOIN account_move m ON m.id = p.move_id
 WHERE m.forum_address_partner_id IN (SELECT id FROM res_partner WHERE name LIKE 'POC-DIR%')
UNION ALL
SELECT 'partners', count(*) FROM res_partner WHERE name LIKE 'POC-DIR%';

-- Desde la interfaz de Odoo es mas seguro: filtrar por 'POC-DIR', revertir los
-- asientos a borrador y borrarlos, despues borrar partners, producto y diario.
