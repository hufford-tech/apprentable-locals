/// <reference path="Globals.js" />

//  States.....................................................
/*
    Set the following variables for STATE
        hiddenStateProvince <-- state abbreviation: Examples CA California, BC British Columbia, PA Pennsylvania...
            needed to get the list of locals associated with this state. 
            $('#hiddenStateProvince').val('') hides State local list 
        hiddenVpDistrict <-- VP that has jurisdiction over that state.  Example: if state is BC, then this value should be 1 
        hiddenFilterOption <-- values are "inside", "outside", "all" ("all" = "")

        See lusStart.htm and go to function... $('a[data-toggle="tab"]').on('shown.bs.tab', function (e)
*/
function CreateStateDropdown() {
    var jParms = { action: "list-states" };
    $.getJSON("DataIO.ashx", jParms, function (jArray) {
        if (jArray.length > 0) {
            LoadStateSelector(jArray);
            $('#ddlStates').chosen();

            $('#ddlStates').chosen().change(function () {
                $('#hiddenStateProvince').val($('#ddlStates').val());
                gState = $('#ddlStates').val();
                $('#hiddenVpDistrict').val($('#ddlStates').find(':selected').attr('District'))
                gDistrict = $('#ddlStates').find(':selected').attr('District');
                //vpFormatInfo();
                //vpFormatInfo($('#ddlStates').find(':selected').attr('District'));

                if ($('#ddlStates').val() != "") {
                    $('.show-state-results').removeClass("btn-default").addClass("btn-primary");
                }
                else {
                    $('.show-state-results').removeClass("btn-primary").addClass("btn-default");
                }
            });

            $('.clear-state-selection').click(function (e) {
                $('#hiddenStateProvince').val("");
                gState = "";
                $('#ddlStates option:selected').prop("selected", false).trigger("chosen:updated");
                $('.show-state-results').removeClass("btn-primary").addClass("btn-default");
                e.preventDefault();
            });

            $('.show-state-results').click(function (e) {
                $('#hiddenFilterOption').val($(this).attr('filter'));
                vpFormatInfo();
                $('#lusTabs a[href="#states"]').tab('show');
                gLUID = "0";
                $('#hiddenLocalID').val("0");
                gLocal = "0";
                $('#hiddenLocalNumber').val("0");
                gDistrict = "0";
                $('#hiddenVpDistrict').val("0");
                //LoadStateResult();
                e.preventDefault();
            });
        }
    });
}

function LoadStateResult() {
    if ($('#hiddenStateProvince').val() != "") {
        //$('#luContent').html('').hide();
        //$('.state-section').fadeIn();
        //var state = $('#hiddenStateProvince').val();
        state = gState;
        $('#lusTabs a[href="#states"]').tab('show');
        //var state = $('#hiddenStateProvince').val();
        var filter = $('#hiddenFilterOption').val();
        if (filter == "") { filter = "All locals"; }
        var title = '<h2>' + state + ' (' + filter + ')</h2>';
        // $('#StateVpContent').html(title);
        
        LoadStateContent();

        //
        //  Set up legacy maps.....................................................................
        //
        //if ($(this).attr('filter') == "outside") {
        if (filter == "outside") {
//            $('#hiddenMapImageUrl').val('http://www.ibew.org/IBEW/directory/images3/' + state + '-Outside.gif');
//            $('#hiddenMapPdfUrl').val('http://www.ibew.org/IBEW/directory/Maps/' + state + '-Outside.pdf');
//            $('#hiddenMapMode').val('static');
//            $('#staticHdr').html('<h4>Outside Jurisdiction Map for ' + state + '</h4>');

            $('#hiddenMapImageUrl').val('');
            $('#hiddenMapPdfUrl').val('');
            $('#hiddenMapMode').val('');
            $('#staticHdr').html('');
        }
        else {
            //if ($(this).attr('filter') == "inside") {
            if (filter == "inside") {
                $('#hiddenMapImageUrl').val('http://www.ibew.org/IBEW/directory/images3/' + state + '-Inside.gif');
                $('#hiddenMapPdfUrl').val('http://www.ibew.org/IBEW/directory/Maps/' + state + '-Inside.pdf');
                $('#hiddenMapMode').val('static');
                $('#staticHdr').html('<h4>Inside Jurisdiction Map for ' + state + '</h4>');
            }
            else {
                $('#hiddenMapImageUrl').val('');
            }
        }
    }

}

function LoadStateSelector(jArray) {
    var wrk = '<option value=""></option>';
    for (var ii = 0; ii < jArray.length; ii++) {
        var o = jArray[ii];
        wrk += '<option value="' + o.StateAbr + '" District="' + o.District + '">' + o.StateName + '</option>';
    }
    $('#ddlStates').html(wrk);
}

//var gState = '';
//var gStFilter = '';

function SetStateContentByLocal(luid) {
    var jParms = { action: "get-local-state-district", lu: luid };
    $.getJSON('DataIO.ashx', jParms, function (jArray) {
        if (jArray.length > 0) {
            var o = jArray[0];
            $('#hiddenStateProvince').val(o.CharterState);
            gState = o.CharterState;
        }
    });
}

function LoadStateContent() {
    $('#stateLocalList').html('');
    gState = $('#hiddenStateProvince').val();
    gStFilter = $('#hiddenFilterOption').val();
    var jParms = { action: "list-locals-by-state", state: gState, filter: gStFilter };
    $.getJSON('DataIO.ashx', jParms, function (jArray) {
        if (jArray.length > 0) {
            $('#stateHeaderTitle').text(gState + ' (' + gStFilter + ')');
            var tbl = '<table class="table table-hover table-condensed"><thead><tr><th>LU</th><th>City</th><th>State</th></tr></thead><tbody>';
            //$('#stateLocalList').html('<table class="table table-hover table-condensed"><thead><tr><th>LU</th><th>City</th><th>State</th></tr></thead><tbody>');
            for (var ii = 0; ii < jArray.length; ii++) {
                var o = jArray[ii];
                tbl += FormatLocalStateListItem(o);
            }
            tbl += '</tbody></table>';
            $('#stateLocalList').html(tbl);

            $('.show-state-local').click(function (e) {
                //alertify.log($(this).attr("lu"));
                $('#hiddenLocalID').val($(this).attr("lu"));
                gLUID = $(this).attr("lu");
                $('#hiddenLocalNumber').val($(this).text());
                gLocal = $(this).text();

                $('#localTab').attr("luid", gLUID);
                $('#localTab').attr("localunion", gLocal);

                $('#hiddenMapMode').val('LU');
                var vp = $(this).attr('District');
                gDistrict = $(this).attr('District');
                $("#hiddenVpDistrict").val(vp);
                $('#lusTabs a[href="#results"]').tab('show');
                //                vpFormatInfo(vp);
                //                LoadLocalContent();
                e.preventDefault();
            });

        }
    });
}
function FormatLocalStateListItem(o) {
    var wrk = '<tr><td><a href="#" class="show-state-local" District="' + o.VP_District + '" lu="' + o.ID + '">' + o.LU + '</a>&nbsp;</td><td>' + o.CharterCity + '&nbsp;</td><td>&nbsp;<span class="badge hand ">' + o.State + '</span></td></tr>';
    return wrk;
    //$('#stateLocalList').append(wrk);
}