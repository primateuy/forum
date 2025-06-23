if (!$.fn.bootstrap_datepicker && $.fn.datepicker && $.fn.datepicker.noConflict) {
    var datepicker = $.fn.datepicker.noConflict();
    $.fn.bootstrap_datepicker = datepicker;
 }