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
        const pickingId = parseInt(ev.target.dataset.pickingId);
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

            return;
        }


        const restante = pedidoCantidad - totalConNuevoValor;
        if (restante > 0 && this.notification) {
            this.notification.add(
                `Cantidad menor. Restante por asignar: ${restante} unidades`,
                { type: 'info' }
            );

            return;
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
        let allLocations = new Set();

        for (const productId in grouped) {
            const product = grouped[productId];
            Object.values(product.locations).forEach(loc => {
                allLocations.add(loc.location_name);
            });
        }

        allLocations = Array.from(allLocations);

        for (const productId in grouped) {
            const product = grouped[productId];
            const row = {
                product_name: product.product_name,
                pedido: product.total_quantity,
                crossdock: product.crossdock,
                default_code: product.default_code,
                uom: product.uom,
                product_id: product.product_id,
                picking_id: product.picking_id,
                picking_name: product.picking_name,

            };


            allLocations.forEach(locName => {
                row[locName] = 0;
            });

            for (const locId in product.locations) {
                const loc = product.locations[locId];
                row[loc.location_name] = loc.quantity;
            }

            table.push(row);
        }


        return {
            rows: table,
            columns: [
                { key: "picking_id", label: "Picking" },
                { key: "product_name", label: "Producto" },
                { key: "pedido", label: "Pedido" },
                { key: "crossdock", label: "Crossdock" },
                ...allLocations.map(loc => ({ key: loc, label: loc }))
            ]
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
                        product_name: item.product_name,
                        picking_id: item.picking_id,
                        picking_name: item.picking_name,
                        default_code: item.product_default_code,
                        uom: item.uom,
                        total_quantity: 0,
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

                // Sumar al total
                groupedByProduct[productId].total_quantity += item.quantity;
            }
        }

        return groupedByProduct;
    }

}

// Register the component
registry.category("actions").add("crossdock_distribution_template", CrossdockDistributionComponent);