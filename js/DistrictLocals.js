/// <reference path="Globals.js" />

// VP Districts....................................
/*
    Set the following variables for VP District
    hiddenVpDistrict <-- VP that has jurisdiction over that state.  Example: if state is BC, then this value should be 1 

    hiddenStateProvince <-- state abbreviation: Examples CA California, BC British Columbia, PA Pennsylvania...
    needed to get the list of locals associated with this state. 
    defaults...
    
        $('#hiddenStateProvince').val('') hides State local list - default
        $('#stateHeaderTitle').html(''); - default
    
    hiddenFilterOption <-- values are "inside", "outside", "all" ("all" = "")

    See lusStart.htm and go to function... $('a[data-toggle="tab"]').on('shown.bs.tab', function (e)
*/

function CreateVpDistrictDropdown() {
    var jParms = { action: "list-vp-districts" };
    $.getJSON("DataIO.ashx", jParms, function (jArray) {
        if (jArray.length > 0) {
            LoadDistrictSelector(jArray);
            $('#ddlDistricts').chosen();

            $('#ddlDistricts').chosen().change(function () {
                $('#hiddenVpDistrict').val($('#ddlDistricts').val());
                $('#hiddenMapMode').val("VP");
                // clear old state list...
                $('#stateLocalList').html('');
                $('#hiddenStateProvince').val('');
                $('#stateHeaderTitle').html('');
                if ($('#ddlDistricts').val() != "0") {
                    $('.show-vp-results').removeClass("btn-default").addClass("btn-primary");
                }
                else {
                    $('.show-vp-results').removeClass("btn-primary").addClass("btn-default");
                }
            });

            $('.clear-vp-selection').click(function (e) {
                $('#hiddenVpDistrict').val("0");
                $('#ddlDistricts option:selected').prop("selected", false).trigger("chosen:updated");
                $('.show-vp-results').removeClass("btn-primary").addClass("btn-default");
                e.preventDefault();
            });

            $('.show-vp-results').click(function (e) {
                if ($('#hiddenVpDistrict').val() != "0") {
                    $('#hiddenFilterOption').val($(this).attr('filter'));
                    $('#hiddenMapMode').val('VP');
                    $('#lusTabs a[href="#districts"]').tab('show');
                    //                    var district = $('#hiddenVpDistrict').val();
                    //                    var filter = $(this).text();
                    //                    LoadDistrictContent(district, filter);
                    //                    vpFormatInfo(district);
                }
                e.preventDefault();
            });
        }
    });
}
function LoadDistrictSelector(jArray) {
    var wrk = '<option value="0"></option>';
    for (var ii = 0; ii < jArray.length; ii++) {
        var o = jArray[ii];
        wrk += '<option value="' + o.DistrictNo + '">' + o.DistrictName + '</option>';
    }
    $('#ddlDistricts').html(wrk);
}

//var gVpFilter = '';
//var gVpDistrict = ''

function SetDistrictContentByLocal(luid) {
    var jParms = { action: "get-local-state-district", lu: luid };
    $.getJSON('DataIO.ashx', jParms, function (jArray) {
        if (jArray.length > 0) {
            var o = jArray[0];
            $('#hiddenVpDistrict').val(o.VP_District, 'ALL');
            gDistrict = o.VP_District;
        }
    });
}

function LoadDistrictContent() {
    $('#vpLocalList').html('');
    gVpFilter = $('#hiddenFilterOption').val();

    //gVpDistrict = $('#hiddenVpDistrict').val();
    gDistrict = $('#hiddenVpDistrict').val();
    var jParms = { action: "list-locals-by-district", district: gDistrict, filter: gVpFilter };
    $.getJSON('DataIO.ashx', jParms, function (jArray) {
        if (jArray.length > 0) {
            // $('#vpHeaderTitle').text('IVP District ' + gVpDistrict + ' (' + gVpFilter + ')');
            //1-10-2020
            //var tbl = '<table class="table table-hover table-condensed"><thead><tr><th>LU</th><th>City</th><th>&nbsp;&nbsp;State</th><th>Google</th></tr></thead><tbody>';
            var tbl = '<table class="table table-hover table-condensed"><thead><tr><th>LU</th><th>City</th><th>&nbsp;&nbsp;State</th></tr></thead><tbody>';
            //$('#vpLocalList').html('<table class="table table-hover table-condensed"><thead><tr><th>LU</th><th>City</th><th>&nbsp;&nbsp;State</th></tr></thead><tbody>');
            for (var ii = 0; ii < jArray.length; ii++) {
                var o = jArray[ii];
                tbl += FormatLocalListItem(o);
            }
            tbl += '</tbody></table>';
            $('#vpLocalList').html(tbl);

 
            $('.show-vp-local').click(function (e) {
                alertify.log($(this).attr("lu"));
                $('#hiddenLocalID').val($(this).attr("lu"));
                gLUID = $(this).attr("lu");
                
                $('#hiddenLocalNumber').val($(this).text());
                gLocal = $(this).text();

                $('#localTab').attr("luid", gLUID);
                $('#localTab').attr("localunion", gLocal);

                $('#hiddenMapMode').val('LU');
                //$('.vp-section').hide();
                $('#lusTabs a[href="#results"]').tab('show');
                //LoadLocalContent();
                e.preventDefault();
            });

            $('span.state-selector').click(function (e) {
                gLUID = "0";
                gLocal = "0";
                $('#hiddenLocalNumber').val("0")
                $('#hiddenStateProvince').val($(this).text());
                gState = $(this).text();
                $('#hiddenVpDistrict').val($(this).attr('District'));
                gDistrict = $(this).attr('District');
                $('#hiddenFilterOption').val(gVpFilter);
                $('#hiddenMapMode').val('LU');
                $('#lusTabs a[href="#states"]').tab('show');
                //                var vp = $(this).attr('District');
                //                vpFormatInfo();
                //                LoadStateContent($(this).text(), gVpFilter)
                e.preventDefault();
            });

            if (gVpFilter != 'outside') {
                //show list of Jurisdictional Maps
              	var tblDistrictMap ='';
              	//var tblDistrictMap = '<table class="table table-hover table-condensed" style="width:250px;"><thead><tr><th><b>District Map</b></th></tr></thead><tbody>';
                //tblDistrictMap += '<tr><td><a href = "javascript:showGMapDistrict();">View map</a ></td></tr>';
                tblDistrictMap += '</tbody></table>';

                var jParmsJmaps = { action: "list-jurisdictional-maps-by-district", district: gDistrict };
                $.getJSON('DataIO.ashx', jParmsJmaps, function (jArray) {
                    if (jArray.length > 0) {
                        var tbl = tblDistrictMap + '<table class="table table-hover table-condensed" style="width:250px;"><thead><tr><th><b>Inside Jurisdictional Map(s)</b></th></tr></thead><tbody>';
                        for (var ii = 0; ii < jArray.length; ii++) {
                            var o = jArray[ii];
                            tbl += '<tr><td><a target="_blank" <a href="./maps/' + o.StateName + '_Inside_Final.pdf">' + o.StateName + '</a></td></tr>';                           
                        }
                        tbl += '</tbody></table>';

                        $('#vpJmapsList').html(tbl);
                    }
                });
            };

        }
    });
     
    }

function FormatLocalListItem(o) {
    var wrk = '<tr><td><a href="#" class="show-vp-local" lu="' + o.ID + '">' + o.LU + '</a>&nbsp;</td><td>';
    wrk += o.CharterCity + '</td><td>&nbsp;<span class="badge state-selector hand" District="' + o.VP_District + '">' + o.CharterState + '</span></td>'
    //wrk += '<td><a target="_blank" href = "./maps/' + o.CharterState + '_Inside_Final.pdf"> Map</a ></td ></tr > ';
    //1-10-2020
    //wrk += '<td><a href = "javascript:showGMapLU('+ o.LU +');"> Map</a ></td ></tr > ';
    return wrk;
    //$('#vpLocalList').append(wrk);
}
function showGMapLU(lu) {
    $('#hiddenMapMode').val('LU');
    gLocal = lu;
    $('#lusTabs a[href="#maps"]').tab('show');

}

function showGMapDistrict() {
    $('#lusTabs a[href="#maps"]').tab('show');
}



