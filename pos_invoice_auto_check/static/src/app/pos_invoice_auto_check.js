/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { _t } from "@web/core/l10n/translation";
import { ConnectionLostError } from "@web/core/network/rpc_service";
import { ConfirmPopup } from "@point_of_sale/app/utils/confirm_popup/confirm_popup";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup();
        this.pos = usePos();
        if (this.pos.config.auto_check_invoice) {
            this.currentOrder.set_to_invoice(true);
        }
    },
    async _finalizeValidation() {
        if (this.pos.config.auto_check_invoice) {
            var self = this;
            if (this.currentOrder.is_paid_with_cash() || this.currentOrder.get_change()) {
                this.hardwareProxy.openCashbox();
            }

            this.currentOrder.date_order = luxon.DateTime.now();

            this.currentOrder.finalized = true;

            let hasError;

            // 1. Save order to server.
            this.env.services.ui.block();
            const syncOrderResult = await this.pos.push_single_order(this.currentOrder);
            this.env.services.ui.unblock();

            if (syncOrderResult instanceof ConnectionLostError) {
                this.pos.showScreen(this.nextScreen);
                return;
            } else if (!syncOrderResult) {
                return;
            }

            try {
                // 2. Invoice.

                if (this.currentOrder.is_to_invoice() && this.pos.config.auto_print_invoice == 'allow_auto_print_invoice') {

                    if (syncOrderResult[0]?.account_move) {
                        if (this.pos.config.email_operation == 'download') {
                            if (syncOrderResult[0]?.account_move) {
                                await this.report.doAction("account.account_invoices", [
                                    syncOrderResult[0].account_move,
                                ]);
                            }
                        }
                        else if (this.pos.config.email_operation == 'send') {
                            const order = await this.orm.call(
                                "pos.order",
                                "send_mail_invoice",
                                [syncOrderResult[0]['id']],
                            );
                        }
                        else if (this.pos.config.email_operation == 'download_send_email') {
                            if (syncOrderResult[0]?.account_move) {
                                await this.report.doAction("account.account_invoices", [
                                    syncOrderResult[0].account_move,
                                ]);
                            }
                            const order = await this.orm.call(
                                "pos.order",
                                "send_mail_invoice",
                                [syncOrderResult[0]['id']],
                            );
                        }
                    } else {
                        throw {
                            code: 401,
                            message: "Backend Invoice",
                            data: { order: this.currentOrder },
                        };
                    }

                    // 3. Post process.
                    if (
                        syncOrderResult &&
                        syncOrderResult.length > 0 &&
                        this.currentOrder.wait_for_push_order()
                    ) {
                        await this.postPushOrderResolve(syncOrderResult.map((res) => res.id));
                    }

                    await this.afterOrderValidation(!!syncOrderResult && syncOrderResult.length > 0);
                }

            } catch (error) {
                if (error instanceof ConnectionLostError) {
                    Promise.reject(error);
                    return error;
                } else {
                    throw error;
                }
            } finally {
                // Always show the next screen regardless of error since pos has to
                // continue working even offline.
                this.pos.showScreen(this.nextScreen);
                // Remove the order from the local storage so that when we refresh the page, the order
                // won't be there
                this.pos.db.remove_unpaid_order(this.currentOrder);

                // Ask the user to sync the remaining unsynced orders.
                if (!hasError && syncOrderResult && this.pos.db.get_orders().length) {
                    const { confirmed } = await this.pos.popup.add(ConfirmPopup, {
                        title: _t('Remaining unsynced orders'),
                        body: _t(
                            'There are unsynced orders. Do you want to sync these orders?'
                        ),
                    });
                    if (confirmed) {
                        // NOTE: Not yet sure if this should be awaited or not.
                        // If awaited, some operations like changing screen
                        // might not work.
                        this.pos.push_orders();
                    }
                }
            }
        } else {
            super._finalizeValidation();
        }
    }
});
