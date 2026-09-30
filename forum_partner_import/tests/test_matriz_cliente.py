# -*- coding: utf-8 -*-
"""Conteo con la matriz del cliente («Disponibilidad Sucursales - Matriz Odoo»).

🔴 El caso reportado: el módulo sólo leía la tabla exportada de Odoo (ALMACENES,
UBICACIONES, 'id' en A3) y con la matriz cortaba en «La celda A3 tiene que decir
'id'». La matriz trae una sola cabecera (IdArtículo | Artículo | ubicaciones),
el producto por referencia interna, negativos y una fila de control del total.
"""
import base64
import io

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None


@tagged('post_install', '-at_install', 'inventario_matriz')
class TestMatrizCliente(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        almacen = env['stock.warehouse'].create({'name': 'Matriz prueba', 'code': 'MTZP'})
        cls.u1 = almacen.lot_stock_id
        cls.u2 = env['stock.location'].create({'name': 'Otra prueba', 'location_id': almacen.view_location_id.id,
                                               'usage': 'internal'})
        PT = env['product.template']
        cls.ok = PT.create({'name': 'Remera matriz OK', 'type': 'product', 'default_code': 'MTZ-001'}).product_variant_id
        cls.por_barra = PT.create({'name': 'Remera matriz barra', 'type': 'product',
                                   'barcode': 'MTZ-002'}).product_variant_id
        cls.dup_a = PT.create({'name': 'Pantalon matriz', 'type': 'product', 'default_code': 'MTZ-DUP'}).product_variant_id
        cls.dup_b = PT.create({'name': 'Campera matriz', 'type': 'product', 'default_code': 'MTZ-DUP'}).product_variant_id
        archivado = PT.create({'name': 'Buzo matriz viejo', 'type': 'product', 'default_code': 'MTZ-ARC'})
        archivado.product_variant_id.active = False
        cls.batch = env['forum.import.batch'].create({
            'name': 'Conteo matriz prueba', 'import_type': 'inventario',
            'inventory_user_id': env.ref('base.user_admin').id,
        })

    def _xlsx(self, filas):
        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.title = 'Importación'
        for fila in filas:
            hoja.append(fila)
        libro.create_sheet('Equivalencias').append(['Donde dice', 'Debo Colocar'])
        buf = io.BytesIO()
        libro.save(buf)
        return base64.b64encode(buf.getvalue())

    def _cargar(self, filas):
        self.batch.write({'inventory_file': self._xlsx(filas), 'inventory_filename': 'matriz.xlsx',
                          'error_log': False})
        self.batch._inv_crear_staging()
        self.batch._inv_leer_xlsx()
        for _etiqueta, paso in self.batch._inv_pasos_post_origen():
            paso()
        self.env.cr.execute(
            "SELECT default_code, ubicacion, cantidad, product_id, error, accion_efectiva "
            "FROM %s ORDER BY fila_excel, col_excel" % self.batch._staging_name())
        return self.env.cr.dictfetchall()

    def _matriz(self):
        n1, n2 = self.u1.complete_name, self.u2.complete_name
        return [
            ['IdArtículo', 'Artículo', n1, n2, None],
            ['MTZ-001', 'Remera matriz OK C:Negro T:M', 5, -2, None],
            ['MTZ-002', 'Remera matriz barra C:Negro T:L', 0, 3, None],
            ['MTZ-DUP', 'Pantalon matriz C:Negro T:S', 1, 1, None],
            ['MTZ-ARC', 'Buzo matriz viejo C:Gris T:M', 4, None, None],
            ['MTZ-NADA', 'Articulo que no existe', 7, None, None],
            ['TOTAL CONTROL - NO IMPORTAR', None, 16, 2, None],
        ]

    def test_lee_la_matriz_y_resuelve_por_codigo(self):
        filas = self._cargar(self._matriz())
        self.assertNotIn('TOTAL CONTROL - NO IMPORTAR', {f['default_code'] for f in filas},
                         "la fila de control no se lee")
        por = {(f['default_code'], f['ubicacion']): f for f in filas}
        ok = por[('MTZ-001', self.u1.complete_name)]
        self.assertEqual((ok['product_id'], ok['cantidad'], ok['error']), (self.ok.id, 5, None))
        barra = por[('MTZ-002', self.u2.complete_name)]
        self.assertEqual(barra['product_id'], self.por_barra.id, "sin referencia, por código de barras")

    def test_negativos_se_admiten(self):
        filas = self._cargar(self._matriz())
        neg = [f for f in filas if f['default_code'] == 'MTZ-001' and f['ubicacion'] == self.u2.complete_name][0]
        self.assertEqual(neg['cantidad'], -2)
        self.assertIsNone(neg['error'])
        self.assertNotEqual(neg['accion_efectiva'], 'error')

    def test_los_errores_dicen_por_que(self):
        filas = self._cargar(self._matriz())
        errores = {f['default_code']: f['error'] for f in filas if f['error']}
        self.assertEqual(set(errores), {'MTZ-DUP', 'MTZ-ARC', 'MTZ-NADA'})
        self.assertIn('Código repetido en Odoo', errores['MTZ-DUP'])
        self.assertIn('Pantalon matriz', errores['MTZ-DUP'])
        self.assertIn('Campera matriz', errores['MTZ-DUP'])
        self.assertIn('[%d]' % self.dup_a.id, errores['MTZ-DUP'])
        self.assertIn('Código de una variante archivada', errores['MTZ-ARC'])
        self.assertIn('Buzo matriz viejo', errores['MTZ-ARC'])
        self.assertIn('Código inexistente en Odoo', errores['MTZ-NADA'])
        self.assertIn('Articulo que no existe', errores['MTZ-NADA'])

    def test_el_log_explica_cada_causa(self):
        self._cargar(self._matriz())
        log = self.batch.error_log
        self.assertIn('matriz del cliente', log)
        self.assertIn('NO IMPORTAR', log)
        self.assertIn('CÓDIGO REPETIDO EN ODOO (1 códigos', log)
        self.assertIn('«Campera matriz» y «Pantalon matriz»', log)
        self.assertIn('en el archivo es «Pantalon matriz»', log)
        self.assertIn('CÓDIGO DE UNA VARIANTE ARCHIVADA (1 códigos', log)
        self.assertIn('MTZ-ARC', log)
        self.assertIn('CÓDIGO INEXISTENTE EN ODOO (1 códigos', log)
        self.assertIn('MTZ-NADA «Articulo que no existe»', log)

    def test_cantidad_en_columna_sin_ubicacion_frena(self):
        matriz = self._matriz()
        matriz[1][4] = 9
        with self.assertRaises(UserError):
            self._cargar(matriz)

    def test_la_tabla_exportada_de_odoo_sigue_andando(self):
        xid = self.ok._export_rows([['id']])[0][0]
        filas = self._cargar([
            ['ALMACENES', None, None, None, None, 'MATRIZ'],
            ['UBICACIONES', None, None, None, None, self.u1.complete_name],
            ['id', 'default_code', 'name', None, None, None],
            [xid, 'MTZ-001', 'Remera matriz OK', None, None, 8],
        ])
        self.assertEqual([(f['product_id'], f['cantidad'], f['error']) for f in filas], [(self.ok.id, 8, None)])

    def test_formato_desconocido_avisa(self):
        with self.assertRaises(UserError) as ctx:
            self._cargar([['Codigo', 'Nombre', 'X'], ['1', 'a', 1], ['2', 'b', 2]])
        self.assertIn('IdArtículo', str(ctx.exception))
