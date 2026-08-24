//  Trade Class dropdowns..........................................................................

function CreateTradeClassDropdown() {
    var jParms = { action: "list-trade-classes" };
    $.getJSON('DataIO.ashx', jParms, function (jArray) {
        if (jArray.length > 0) {
            LoadTradeClassSelector(jArray);
        }
        $('#ddlTradeClasses').chosen();
    });
    jParms = { action: "list-states" };
    $.getJSON('DataIO.ashx', jParms, function (jArray) {
        if (jArray.length > 0) {
            LoadTradeClassStateSelector(jArray);
        }
        $('#ddlTcStates').chosen();
    });

    $('.clear-tc-selection').click(function (e) {
        $('#hiddenTradeClassList').val("");
        $('#hiddenStateList').val("");

        $('#ddlTradeClasses option:selected').removeAttr("selected");
        $('#ddlTradeClasses option:eq(0)').prop("selected", true).trigger("chosen:updated"); 

        $('#ddlTcStates option:selected').removeAttr("selected");
        $('#ddlTcStates option:eq(0)').prop("selected", true).trigger("chosen:updated");

        //$('.show-state-results').removeClass("btn-primary").addClass("btn-default");
        e.preventDefault();
    });

    $('.show-tc-results').click(function (e) {
        $('#hiddenTradeClassList').val($('#ddlTradeClasses').val());
        $('#hiddenStateList').val($('#ddlTcStates').val());
        $('#lusTabs a[href="#tradeclass"]').tab('show');
        alertify.log($('#hiddenTradeClassList').val());
        alertify.log($('#hiddenStateList').val());
        LoadTradeClassAccordian();
        e.preventDefault();
    });

    $('#ddlTradeClasses').change(function (e) {
        if ($(this).val() != "ALL") {
            $('#ddlTradeClasses option:eq(0)').prop("selected", false).trigger("chosen:updated");
        }
    });
    $('#ddlTcStates').change(function (e) {
        if ($(this).val() != "ALL") {
            $('#ddlTcStates option:eq(0)').prop("selected", false).trigger("chosen:updated");
        }
    });

}

function LoadTradeClassSelector(jArray) {
    var wrk = '<option value="ALL" selected>All Classifications</option>';
    for (var ii = 0; ii < jArray.length; ii++) {
        var o = jArray[ii];
        wrk += LoadTradeClassItem(o);
    }
    $('#ddlTradeClasses').html(wrk);
}

function LoadTradeClassItem(o) {
    var wrk = '<option value="' + o.Abbreviation + '">' + o.ClassTypes + '</option>';
    return wrk;
}

function LoadTradeClassStateSelector(jArray) {
    var wrk = '<option value="ALL" selected>All States/Provinces</option>';
    for (var ii = 0; ii < jArray.length; ii++) {
        var o = jArray[ii];
        wrk += LoadTradeClassStateItem(o);
    }
    $('#ddlTcStates').html(wrk);
}

function LoadTradeClassStateItem(o) {
    var wrk = '<option value="' + o.StateAbr + '" District="' + o.District + '">' + o.StateName + '</option>';
    return wrk;
}

//  Trade Class Accordian for "ALL" or selected tradeclasses.......................................

var classification = '';

function LoadTradeClassAccordian() {
    var tclist = $('#hiddenTradeClassList').val();
    var stlist = $('#hiddenStateList').val();
    var jParms = { action: "list-sel-trade-classes", tradeclasses: tclist, states: stlist };
    $.getJSON('DataIO.ashx', jParms, function (jArray) {
        if (jArray.length > 0) {
            var acc = '';
            $('#tcContent').html('');
            for (var ii = 0; ii < jArray.length; ii++) {
                var o = jArray[ii];
                acc = '<div class="panel panel-default">';
                acc += '<div class="panel-heading">';
                acc += '<h5 class="panel-title">';
                acc += '<a data-toggle="collapse" class="active-tradeclass" data-parent="#accordion" tc="' + o.TradeClassDesc + '" href="#tc_' + o.TradeClassDesc + '">' + o.ClassTypes + ' (' + o.CNT + ')</a>';
                acc += '</h5>';
                acc += '</div>';
                acc += '<div id="tc_' + o.TradeClassDesc + '" class="panel-collapse collapse">';
                acc += '<div class="panel-body"></div>';
                acc += '</div>';
                acc += '</div>';
                $('#tcContent').append(acc);
            }

            $('.active-tradeclass').click(function (e) {
                classification = $(this).attr('tc');
                $(this)
                e.preventDefault();
            });
            $('#tcContent').on('shown.bs.collapse', function () {
                
                BuildStateTradClassLocals();
                
            });
        }
    });
}

function BuildStateTradClassLocals() {
    var jParms = { action: "list-state-trade-class-locals", tradeclass: classification, states: $('#hiddenStateList').val() };
    $.getJSON('DataIO.ashx', jParms, function (jArray) {
        if (jArray.length > 0) {
            var tbl = '<table class="table table-condensed table-hover"><thead><tr><th>LU</th><th>City</th><th>State</th></tr></thead><tbody>';
            //$('#tc_' + classification + ' div.panel-body').html('<table class="table"><thead><tr><th>LU</th><th>City</th><th>State</th></tr></thead><tbody>');
            for (var ii = 0; ii < jArray.length; ii++) {
                var o = jArray[ii];
                var target = 'tc_' + classification;
                tbl += FormatStateTradeClassLocals(o);
            }
            tbl += '</tbody></table>';
            $('#tc_' + classification + ' div.panel-body').html(tbl);

            $('.show-tc-local').click(function (e) {
                $('#hiddenLocalID').val($(this).attr("lu"));
                $('#hiddenLocalNumber').val($(this).text());
                $('#hiddenMapMode').val('LU');
                $('#hiddenFilterOption').val(classification);
                $('#lusTabs a[href="#results"]').tab('show');
                //LoadLocalContent();
                e.preventDefault();
            });

            $('.state-tradeclass').click(function (e) {
                var st = $(this).text();
                $('#hiddenStateProvince').val(st);
                var vp = $(this).attr('District');
                $('#hiddenVpDistrict').val(vp);
                $('#hiddenMapMode').val('static');
                $('#hiddenFilterOption').val(classification);
                $('#stateHeaderTitle').html('<h3>' + st + ' (' + classification + ')</h3>');
                $('#lusTabs a[href="#states"]').tab('show');
                //vpFormatInfo(vp);
                //LoadStateContent(st, classification);
                e.preventDefault();
            });
        }
    });
}
function FormatStateTradeClassLocals(o) {
    var wrk = '<tr><td><a href="#" class="show-tc-local" lu="' + o.ID + '">' + o.LU + '</a>&nbsp;</td><td>' + o.CharterCity + '&nbsp;</td><td>&nbsp;<span class="badge hand state-tradeclass" District="' + o.VP_District + '">' + o.CharterState + '</span></td></tr>';
    return wrk;
    //$('#tc_' + classification + ' div.panel-body').append(wrk);
}

