/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

class CrossdockDistributionComponent extends Component {
    static template = "crossdock_distribution_template";
    static components = { Dialog };

    setup() {
        this.state = useState({
            distributionData: {},
            loading: true,
            error: null
        });

        // Services
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification"); // Add this for error/success messages

        onWillStart(async () => {
            await this.loadData();
        });
    }

    onInputChange(ev, row, col) {
        const productId = parseInt(ev.target.dataset.productId);
        const pickingId = col.picking_id || this.state.distributionData.locationPickings.get(col.key)?.picking_id;
        const newQuantity = parseInt(ev.target.value) || 0;
        const pedidoCantidad = row.pedido;
        const currentQuantity = row[col.key] || 0;

        let totalConNuevoValor = 0;

        this.state.distributionData.columns.forEach(column => {
            if (column.key !== 'picking_id' &&
                column.key !== 'product_name' &&
                column.key !== 'pedido' &&
                column.key !== 'crossdock') {

                if (column.key === col.key) {
                    totalConNuevoValor += newQuantity;
                } else {
                    totalConNuevoValor += (row[column.key] || 0);
                }
            }
        });

        if (totalConNuevoValor > pedidoCantidad) {
            const exceso = totalConNuevoValor - pedidoCantidad;

            if (this.notification) {
                this.notification.add(
                    `Error: La cantidad total (${totalConNuevoValor}) excede el pedido (${pedidoCantidad}). Exceso: ${exceso} unidades.`,
                    { type: 'danger' }
                );
            } else {
                alert(`Error: La cantidad total (${totalConNuevoValor}) excede el pedido (${pedidoCantidad}). Exceso: ${exceso} unidades.`);
            }

            ev.target.value = currentQuantity;

            // Don't proceed with update
            return;
        }



        const restante = pedidoCantidad - totalConNuevoValor;
        if (restante > 0 && this.notification) {
            this.notification.add(
                `Cantidad menor. Restante por asignar: ${restante} unidades`,
                { type: 'info' }
            );

        } else if (restante === 0 && this.notification) {
            this.notification.add(
                `✓ Pedido completo asignado (${pedidoCantidad} unidades)`,
                { type: 'success' }
            );
        }

        row[col.key] = newQuantity;


        this.orm.call("stock.picking", "updatePickingQuantity", [pickingId, productId, newQuantity])
            .then(result => {
                if (!result || !result.success) {

                    row[col.key] = currentQuantity;
                    ev.target.value = currentQuantity;

                    if (this.notification) {
                        this.notification.add(
                            result.error || 'Error al actualizar en el servidor',
                            { type: 'danger' }
                        );
                    }
                }
            })
            .catch(error => {

                row[col.key] = currentQuantity;
                ev.target.value = currentQuantity;

                if (this.notification) {
                    this.notification.add(
                        'Error de conexión al actualizar cantidad',
                        { type: 'danger' }
                    );
                }
            });

    }



    get dialogProps() {
        return {
            title: "Distribución Crossdock",
            size: "lg",
            footer: this.renderFooter.bind(this)
        };
    }

    onCancel() {

        this.env.services.action.doAction({
            type: 'ir.actions.act_window_close'
        });
    }



    async loadData() {
        const ctx = this.props.action.context;

        const grouped = this.groupByProduct(ctx);

        const tableData = this.transformForTable(grouped);


        this.state.distributionData = tableData;
        this.state.loading = false;
    }


    transformForTable(grouped) {
        const table = [];
        let allLocations = new Map(); // Usar Map en lugar de Set

        // Recopilar locations con su info completa
        for (const productId in grouped) {
            const product = grouped[productId];
            Object.values(product.locations).forEach(loc => {
                allLocations.set(loc.location_name, {
                    location_name: loc.location_name,
                    picking_id: loc.picking_id,
                    picking_name: loc.picking_name
                });
            });
        }

        for (const productId in grouped) {
            const product = grouped[productId];
            const row = {
                product_name: product.product_name,
                pedido: product.total_quantity,
                crossdock: product.crossdock,
                default_code: product.default_code,
                uom: product.uom,
                product_id: product.product_id,
            };

            // Inicializar todas las locations
            allLocations.forEach((locInfo, locName) => {
                row[locName] = 0;
            });

            // Llenar con las cantidades reales
            for (const locId in product.locations) {
                const loc = product.locations[locId];
                row[loc.location_name] = loc.quantity;
            }

            table.push(row);
        }

        return {
            rows: table,
            columns: [
                { key: "product_name", label: "Producto" },
                { key: "pedido", label: "Pedido" },
                { key: "crossdock", label: "Crossdock" },
                ...Array.from(allLocations.entries()).map(([locName, locInfo]) => ({
                    key: locName,
                    label: `${locName} (${locInfo.picking_name})`,
                    picking_id: locInfo.picking_id // ← Info del picking en la columna
                }))
            ],
            locationPickings: allLocations // Info completa de locations
        };
    }


    groupByProduct(data) {
        const groupedByProduct = {};

        for (const key in data) {
            const item = data[key];

            if (item && typeof item === 'object' && item.product_id) {
                const productId = item.product_id;

                if (!groupedByProduct[productId]) {
                    groupedByProduct[productId] = {
                        product_id: item.product_id,
                        crossdock: item.crossdock,
                        product_name: item.product_display,
                        picking_id: item.picking_id,
                        picking_name: item.picking_name,
                        default_code: item.product_default_code,
                        uom: item.uom,
                        total_quantity: item.total_line_quantity,
                        warehouses: {},
                        locations: {}
                    };
                }

                const warehouseId = item.source_warehouse_id;
                if (!groupedByProduct[productId].warehouses[warehouseId]) {
                    groupedByProduct[productId].warehouses[warehouseId] = {
                        warehouse_id: warehouseId,
                        warehouse_name: item.source_warehouse_name,
                        quantity: 0
                    };
                }
                groupedByProduct[productId].warehouses[warehouseId].quantity += item.quantity;


                const locationId = item.destination_location_id;
                if (!groupedByProduct[productId].locations[locationId]) {
                    groupedByProduct[productId].locations[locationId] = {
                        location_id: locationId,
                        location_name: item.destination_location_name,
                        picking_id: item.picking_id,
                        picking_name: item.picking_name,
                        quantity: 0
                    };
                }
                groupedByProduct[productId].locations[locationId].quantity += item.quantity;

            }
        }

        return groupedByProduct;
    }


    async findAndUpdateStockMove(pickingId, productId, newQuantity) {
        try {
            // Buscar el stock.move específico
            const moveIds = await this.orm.searchRead(
                "stock.move",
                [
                    ["picking_id", "=", pickingId],
                    ["product_id", "=", productId]
                ],
                ["id", "product_uom_qty", "quantity_done", "state"]
            );

            if (moveIds.length > 0) {
                const move = moveIds[0]; // Tomar el primero si hay varios

                // Actualizar la cantidad demandada
                const result = await this.orm.call(
                    "stock.move",
                    "write",
                    [move.id, { "product_uom_qty": newQuantity }]
                );

                return { success: true, move_id: move.id };
            } else {
                return { success: false, error: 'No se encontró el movimiento' };
            }
        } catch (error) {
            return { success: false, error: error.message };
        }
    }

}



// Register the component
registry.category("actions").add("crossdock_distribution_template", CrossdockDistributionComponent);