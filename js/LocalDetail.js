

//  Local Selector Functions...............................................................
function CreateLocalDropdown() {
    var jParms = { action: "list-locals" };
    $.getJSON("DataIO.ashx", jParms, function (jArray) {
        if (jArray.length > 0) {
            LoadLocalSelector(jArray);
            $('#ddlLocals').chosen();

            $('#ddlLocals').chosen().change(function () {
                $('#hiddenLocalID').val($('#ddlLocals').val());
                gLUID = $('#ddlLocals').val();
                $('#hiddenLocalNumber').val($('#ddlLocals option:selected').text());
                gLocal = $('#ddlLocals option:selected').text();

                $('#localTab').attr("luid", gLUID);
                $('#localTab').attr("localunion", gLocal);

                $('#hiddenMapMode').val("LU");
                if ($('#ddlLocals').val() != "0") {
                    $('.show-local-results').removeClass("btn-default").addClass("btn-primary");
                }
                else {
                    $('.show-local-results').removeClass("btn-primary").addClass("btn-default");
                }
            });

            $('.clear-local-selection').click(function (e) {
                $('#hiddenLocalID').val("0");
                gLUID = '0';
                gLocal = '0';
                $('#ddlLocals option:selected').prop("selected", false).trigger("chosen:updated");
                $('.show-local-results').removeClass("btn-primary").addClass("btn-default");
                e.preventDefault();
            });

            $('.show-local-results').click(function (e) {
                if ($('#hiddenLocalID').val() != "0") {
                    $('#lusTabs a[href="#results"]').tab('show');
                    // LoadLocalContent();
                }
                e.preventDefault();
            });

        }
        else {
            alertify.error("Unable to query database");
        }
    }).error(function () {
        alertify.error("Unable to query database");
    });
}



function LoadLocalSelector(jArray) {
    var wrk = '<option value="0"></option>';
    for (var ii = 0; ii < jArray.length; ii++) {
        var o = jArray[ii];
        wrk += '<option value="' + o.ID + '">' + o.LU + '</option>';
    }
    $('#ddlLocals').html(wrk);
}
function LoadLocalContent() {

    var lu = $('#hiddenLocalID').val();
    if (lu === "0") {
        $('#lusTabs a[href="#search"]').tab('show');
    }
    else {
        var jParms = { action: "show-local-info", LocalUnionID: $('#hiddenLocalID').val() };
        $.getJSON("DataIO.ashx", jParms, function (jArray) {
            FormatLocalContent(jArray);
        });
        jParms = { action: "list-local-trade-classes", LocalUnionID: $('#hiddenLocalID').val() };
        $.getJSON("DataIO.ashx", jParms, function (jArray) {
            FormatLocalClassifications(jArray);
        });
        SetStateContentByLocal($('#hiddenLocalID').val());
        SetDistrictContentByLocal($('#hiddenLocalID').val());
        // var jobs = 'http://www.ibew.org/jobsboard/JBResponse.aspx?LU=' + $('#hiddenLocalNumber').val();
        var jobs = 'http://www.ibew.org/Tools/Construction-Jobs-Board';
        $('#luJobsBroad').prop('href', jobs);
    }
    //$('#luJobsBroad').html('<a href="' + jobs + '" target="_blank">Construction Jobs Board</a>');
}
function FormatLocalClassifications(jArray) {
    if (jArray.length > 0) {
        var wrk = '<br/><b>Classifications</b><br/><span class="indent2">';
        for (var ii = 0; ii < jArray.length; ii++) {
            var o = jArray[ii];
            wrk += o.TradeClass + "<br/>";
        }
        wrk += '</span>';
        $('#luTradeClass').html(wrk);
    }
}
function FormatLocalContent(jData) {
    jEditData = jData;
    var line = '';
    var wrk = '';
    for (var ii = 0; ii < jData.length; ii++) {
        line = jData[ii].Line;
        if (line != '') {
            line = line.replace(/\[t\]/, '<span class="indent2" index="' + ii + '">');
            line = line.replace(/\[t\]/, '<span class="indent3">');
            line = line.replace(/\[b\]/g, '<b>');
            line = line.replace(/\[\/b\]/g, '</b>');
            line = line.replace(/\[\/t\]/g, '</span>');
            if (ii == 0) {
                line = '<span index="0">' + line + '</span>';
            }
            wrk += line + '<br />';
        }
    }
    $('#luContent').html(wrk);
}