/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { ProductsWidget } from "@point_of_sale/app/screens/product_screen/product_list/product_list";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { Order, Orderline, Payment } from "@point_of_sale/app/store/models";
import { _t } from "@web/core/l10n/translation";
import { ProductInfoPopup } from "@point_of_sale/app/screens/product_screen/product_info_popup/product_info_popup";
var flag = false;

patch(ProductsWidget.prototype, {
    setup() {
        super.setup();
        this.pos = usePos();
        onMounted(this.onMounted);
    },

    /**
     * Placeholder del buscador de productos en el PDV (traducible vía i18n).
     */
    get productSearchPlaceholder() {
        return _t("Search products...");
    },

    /**
     * Etiquetas de columnas de la vista lista de productos (traducibles vía i18n).
     */
    get listHeaderImage() {
        return _t("Image");
    },
    get listHeaderCode() {
        return _t("Code");
    },
    get listHeaderName() {
        return _t("Name");
    },
    get listHeaderType() {
        return _t("Type");
    },
    get listHeaderUom() {
        return _t("UoM");
    },
    get listHeaderPrice() {
        return _t("Price");
    },
    get listHeaderOnHandQty() {
        return _t("On Hand Qty");
    },
    get listHeaderForecastedQty() {
        return _t("Forecasted Qty");
    },

    /**
     * Devuelve la etiqueta traducida del tipo de producto para la grilla lista.
     */
    getProductTypeLabel(type) {
        if (type === "consu") {
            return _t("Consumable");
        }
        if (type === "service") {
            return _t("Service");
        }
        if (type === "product") {
            return _t("Storable Product");
        }
        return "";
    },
    onMounted() {
        if(this.pos.config.prod_view === 'list' && this.pos.config.enable_list_view){
            if(flag=true){
                $('.product-list').addClass('d-none')
                $('.product-list-container-view').show()
            }
            else{
                $('.product-list').removeClass('d-none')
                $('.product-list-container-view').addClass('d-none');
            }
        }
        else if (this.pos.config.prod_view === 'grid' && this.pos.config.enable_list_view){
            $('.product-list-container-view').addClass('d-none');
        }
    },
    get imageUrl() {
        const product = this.prd.id
         return `/web/image?model=product.product&field=image_128&id=${product}&unique=${product.write_date}`;
    },
    get pricelist() {
        const current_order = this.env.services.pos.get_order();
        if (current_order) {
            return current_order.pricelist;
        }
        return this.env.services.pos.default_pricelist;
    },
    get price() {
        const product = this.prd
        const formattedUnitPrice = this.env.utils.formatCurrency(product.get_display_price());
        if (this.to_weight) {
            return `${formattedUnitPrice}/${this.get_unit().name}`;
        } else {
            return formattedUnitPrice;
        }
    },
    get productsToDisplay() {
        const { db } = this.pos;
        this.Changeview()
        if (this.searchWord !== "") {
            return db.search_product_in_category(this.selectedCategoryId, this.searchWord);
        } else {
            var AscName, DescName, LowToHighPrice, HighToLowPrice;
            var product = db.get_product_by_category(this.selectedCategoryId);
            if(flag == true){
                $('.product-list').hide()
            }
            if(this.pos.config.product_ordering == "a_to_z") {
                function SortByNameAsc(firstName, secondName){
                    var firstName = firstName.name.toLowerCase();
                    var secondName = secondName.name.toLowerCase();
                    var final_name_asc = ((firstName < secondName) ? -1 : ((firstName > secondName) ? 1 : 0));
                    return final_name_asc
                }
                AscName = product.sort(SortByNameAsc);
                return AscName;
            } else if (this.pos.config.product_ordering == "z_to_a"){
                function SortByNameDesc(firstName, secondName){
                    var firstName = firstName.name.toLowerCase();
                    var secondName = secondName.name.toLowerCase();
                    var final_name_desc = ((firstName > secondName) ? -1 : ((firstName < secondName) ? 1 : 0));
                    return final_name_desc;
                }
                DescName = product.sort(SortByNameDesc);
                return DescName;
            } else if (this.pos.config.product_ordering == "low_to_high"){
                function SortByPriceLowToHigh(firstPrice, secondPrice){
                    var firstPrice = firstPrice.lst_price;
                    var secondPrice = secondPrice.lst_price;
                    var final_price_low_to_high = parseFloat(firstPrice) - parseFloat(secondPrice);
                    return final_price_low_to_high
                }
                LowToHighPrice = product.sort(SortByPriceLowToHigh);
                return LowToHighPrice;
            } else if (this.pos.config.product_ordering == "high_to_low") {
                function SortByPriceHighToLow(firstPrice, secondPrice){
                    var firstPrice = firstPrice.lst_price;
                    var secondPrice = secondPrice.lst_price;
                    var final_price_high_to_low = parseFloat(secondPrice) - parseFloat(firstPrice);
                    return final_price_high_to_low
                }
                HighToLowPrice = product.sort(SortByPriceHighToLow);
                return HighToLowPrice;
            } else {
                return product;
            }
        }
    },
    Changeview(){
        if (this.pos.config.enable_list_view){
            var self = this;
            $('.code').click(function(){
                var table, i, x, y,dir,switchcount=0;;
                table = document.getElementById("id01");
                var switching = true;
                dir = "asc";
                while (switching){
                    switching = false;
                    var rows = table.rows;
                    for (i = 1; i < (rows.length - 1); i++){
                        var Switch = false;
                        x = rows[i].getElementsByClassName("product_code")[0];
                        y = rows[i + 1].getElementsByClassName("product_code")[0];
                        if(dir== "asc"){
                            if (x.innerHTML.toLowerCase() > y.innerHTML.toLowerCase()){

                                Switch = true;
                                break;
                            }
                        }
                        else if (dir == "desc") {
                            if (x.innerHTML.toLowerCase() < y.innerHTML.toLowerCase()) {
                                Switch = true;
                                break;
                            }
                        }
                    }
                    if (Switch) {
                        rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                        switching = true;
                        switchcount ++;
                    } else {
                        if (switchcount == 0 && dir == "asc") {
                            dir = "desc";
                            switching = true;
                        }
                    }
                }
            });

            $('.name').click(function(){
                var table, i, x, y,dir,switchcount=0;;
                table = document.getElementById("id01");
                var switching = true;
                dir = "asc";
                while (switching){
                    switching = false;
                    var rows = table.rows;
                    for (i = 1; i < (rows.length - 1); i++){
                        var Switch = false;
                        x = rows[i].getElementsByClassName("product_name")[0];
                        y = rows[i + 1].getElementsByClassName("product_name")[0];
                        if(dir== "asc"){
                            if (x.innerHTML.toLowerCase() > y.innerHTML.toLowerCase()){
                                Switch = true;
                                break;
                            }
                        }
                        else if (dir == "desc") {
                            if (x.innerHTML.toLowerCase() < y.innerHTML.toLowerCase()) {
                                Switch = true;
                                break;
                            }
                        }
                    }
                    if (Switch) {
                        rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                        switching = true;
                        switchcount ++;
                    } else {
                        if (switchcount == 0 && dir == "asc") {
                            dir = "desc";
                            switching = true;
                        }
                    }
                }
            });

            $('.type').click(function(){
                var table, i, x, y,dir,switchcount=0;;
                table = document.getElementById("id01");
                var switching = true;
                dir = "asc";
                while (switching){
                    switching = false;
                    var rows = table.rows;
                    for (i = 1; i < (rows.length - 1); i++){
                        var Switch = false;
                        x = rows[i].getElementsByClassName("product_type")[0];
                        y = rows[i + 1].getElementsByClassName("product_type")[0];
                        if(dir== "asc"){
                            if (x.innerHTML.toLowerCase() > y.innerHTML.toLowerCase()){
                                Switch = true;
                                break;
                            }
                        }
                        else if (dir == "desc") {
                            if (x.innerHTML.toLowerCase() < y.innerHTML.toLowerCase()) {
                                Switch = true;
                                break;
                            }
                        }
                    }
                    if (Switch) {
                        rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                        switching = true;
                        switchcount ++;
                    } else {
                        if (switchcount == 0 && dir == "asc") {
                            dir = "desc";
                            switching = true;
                        }
                    }
                }
            });

            $('.uom').click(function(){
                var table, i, x, y,dir,switchcount=0;;
                table = document.getElementById("id01");
                var switching = true;
                dir = "asc";
                while (switching){
                    switching = false;
                    var rows = table.rows;
                    for (i = 1; i < (rows.length - 1); i++){
                        var Switch = false;
                        x = rows[i].getElementsByClassName("product_uom")[0];
                        y = rows[i + 1].getElementsByClassName("product_uom")[0];
                        if(dir== "asc"){
                            if (x.innerHTML.toLowerCase() > y.innerHTML.toLowerCase()){
                                Switch = true;
                                break;
                            }
                        }
                        else if (dir == "desc") {
                            if (x.innerHTML.toLowerCase() < y.innerHTML.toLowerCase()) {

                                Switch = true;
                                break;
                            }
                        }
                    }
                    if (Switch) {
                        rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                        switching = true;
                        switchcount ++;
                    } else {
                        if (switchcount == 0 && dir == "asc") {
                            dir = "desc";
                            switching = true;
                        }
                    }
                }
            });

            $('.price').click(function(){

                var table, i, x, y,z,dir,switchcount=0;
                table = document.getElementById("id01");
                var switching = true;
                dir = "asc";
                while (switching){
                    switching = false;
                    var rows = table.rows;
                    for (i = 1; i < (rows.length - 1); i++){
                        var Switch = false;
                        x = rows[i].getElementsByClassName("product_price")[0];
                        y = rows[i + 1].getElementsByClassName("product_price")[0];
                        z = x.innerHTML.split(";")[1].split(",").join("")
                        if(dir== "asc"){
                            if (parseFloat(x.innerHTML.split(";")[1].split(",").join("")) > parseFloat(y.innerHTML.split(";")[1].split(",").join(""))){
                                Switch = true;
                                break;
                            }
                        }
                        else if (dir == "desc") {
                            if (parseFloat(x.innerHTML.split(";")[1].split(",").join("")) < parseFloat(y.innerHTML.split(";")[1].split(",").join(""))) {
                                Switch = true;
                                break;
                            }
                        }
                    }
                    if (Switch) {
                        rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                        switching = true;
                        switchcount ++;
                    } else {
                        if (switchcount == 0 && dir == "asc") {
                            dir = "desc";
                            switching = true;
                        }
                    }
                }

            });
            $('.qty').click(function(){
                var table, i, x, y ,dir,switchcount=0;
                table = document.getElementById("id01");
                var switching = true;
                dir = "asc";
                while (switching){
                    switching = false;
                    var rows = table.rows;
                    for (i = 1; i < (rows.length - 1); i++){
                        var Switch = false;
                        x = rows[i].getElementsByClassName("on_hand_qty")[0];
                        y = rows[i + 1].getElementsByClassName("on_hand_qty")[0];
                        if(dir== "asc"){
                            if (parseInt(x.innerHTML) > parseInt(y.innerHTML)){

                                Switch = true;
                                break;
                            }
                        }
                        else if (dir == "desc") {
                            if (parseInt(x.innerHTML) < parseInt(y.innerHTML)) {

                                Switch = true;
                                break;
                            }
                        }
                    }
                    if (Switch) {
                        rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                        switching = true;
                        switchcount ++;
                    } else {
                        if (switchcount == 0 && dir == "asc") {
                            dir = "desc";
                            switching = true;
                        }
                    }
                }
            });
            $('.fqty').click(function(){
                var table, i, x, y ,dir,switchcount=0;
                table = document.getElementById("id01");
                var switching = true;
                dir = "asc";
                while (switching){
                    switching = false;
                    var rows = table.rows;
                    for (i = 1; i < (rows.length - 1); i++){
                        var Switch = false;
                        x = rows[i].getElementsByClassName("forecast_qty")[0];
                        y = rows[i + 1].getElementsByClassName("forecast_qty")[0];
                        if(dir== "asc"){
                            if (parseInt(x.innerHTML) > parseInt(y.innerHTML)){

                                Switch = true;
                                break;
                            }
                        }
                        else if (dir == "desc") {
                            if (parseInt(x.innerHTML) < parseInt(y.innerHTML)) {

                                Switch = true;
                                break;
                            }
                        }
                    }
                    if (Switch) {
                        rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                        switching = true;
                        switchcount ++;
                    } else {
                        if (switchcount == 0 && dir == "asc") {
                            dir = "desc";
                            switching = true;
                        }
                    }
                }
            });
            $('.js-category-list').click(function(){
                flag = true;
                $('.product-list-container-view').removeClass('d-none');
                $('.product-list').addClass('d-none');
            });
            $('.js-category-switch').click(function(){
                flag = false;
                $('.product-list').removeClass('d-none');
                $('.product-list-container-view').addClass('d-none');
            });
        }    
    }
});