/** @odoo-module **/

import { WebClient } from "@web/webclient/webclient";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { patch } from "@web/core/utils/patch";

patch(WebClient.prototype, {
    setup() {
        super.setup();
        this.force_fullscreen = false
        const hash = window.location.hash.substring(1);
        const params = new URLSearchParams(hash);
        if(params.get('iframe_fullscreen') && params.get('iframe_fullscreen') == 'true'){
            this.force_fullscreen = true
            this.checkTidio()
        };
    },
    checkTidio(){
        const self = this
        let elapsedTime = 0;
        const maxDuration = 10000;
        function checkForElement() {
            var tidio = document.getElementById('tidio-chat');
            if (tidio) {
                tidio.classList.add('d-none');
                clearInterval(intervalId); 
            } else {
                elapsedTime += 1000; 
                if (elapsedTime >= maxDuration) {
                    clearInterval(intervalId); 
                }
            }
        }
        const intervalId = setInterval(checkForElement, 1000);
    }
});

patch(ControlPanel.prototype, {
    setup() {
        super.setup();
        this.force_fullscreen = false
        if (window.self !== window.top){
            this.force_fullscreen = true
        }
    }
})