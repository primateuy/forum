// Dropdown, Datepicker and Collapse are not working in Odoo Version 16
// So this is the manual event listener
$(function () {
    $('body').on('click', '.izi_view', function (ev) {
        ev.stopPropagation();
        elmId = $(ev.currentTarget);

        $('.dropdown-menu').hide();
    });

    $('body').on('click', '.izi_view .dropdown-toggle', function (ev) {
        ev.stopPropagation();
        elmId = $(ev.currentTarget);

        if (($(elmId).parents().find('.izi_view').length) >= 1) {
            if ($(elmId).hasClass('show') || $(elmId).parent().find('.dropdown-menu').css('display') == 'none') {
                $(elmId).removeClass('.dropdown-menu');
                $('.dropdown-menu').hide();
                $(elmId).addClass('.dropdown-menu');
                $(elmId).removeClass('show');
                $(elmId).parent().find('.dropdown-menu').show();
            } else {
                $(elmId).removeClass('.dropdown-menu');
                $('.dropdown-menu').hide();
                $(elmId).addClass('.dropdown-menu');
                $(elmId).addClass('show');
                $(elmId).parent().find('.dropdown-menu').hide();
            }
        }


    });

    $('body').on('click', '.izi_view .o_datepicker', function (ev) {
        ev.stopPropagation();
        elmId = $(ev.currentTarget);

        if (($(elmId).parents().find('.izi_view').length) >= 1) {
            $('.bootstrap-datetime-picker').show();
        }
    });
    $('body').on('click', '.izi_view [data-toggle="collapse"]', function (ev) {
        ev.stopPropagation();
        elmId = $(ev.currentTarget).data('target');

        if (($(elmId).parents().find('.izi_view').length) >= 1) {
            if ($(elmId).hasClass('show')) {
                $(elmId).removeClass('show');
            } else {
                $(elmId).addClass('show');
            }
        };
    });
});