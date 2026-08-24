var selectedCounty = '';
var OhCanada = 'N';

function GetCountyList(listType) {

    var jParms = { action: "county-list", type: listType, vp: $('#hiddenVpDistrict').val(), state: $('#hiddenStateProvince').val() };
    var county = $.getJSON('DataIO.ashx', jParms, "JSON");
    OhCanada = 'N';

    if ($('#hiddenVpDistrict').val() == "1") {
        OhCanada = 'Y';
    }

    county.done(function (jArray) {
        if (jArray.length > 0) {
            var opt = '<option value=""></option>';
            for (var ii = 0; ii < jArray.length; ii++) {
                var o = jArray[ii];
                opt += '<option value="' + o.CountyName + '">' + o.CountyName + '</option>';
            }
            if (listType == 'vp') {

                $('#ddlVpCounties').html('').html(opt).attr("Canada", OhCanada);
                $('#ddlVpCounties').chosen();
                CountyListEvents('ddlVpCounties');
            }
            else {
                $('#ddlStateCounties').html('').html(opt).attr("Canada", OhCanada);
                $('#ddlStateCounties').chosen();
                CountyListEvents('ddlStateCounties');
            }
        }
    });

    county.fail(function () {
        alertify.error("Error: No counties found");
    });

    county.always(function () {
        if (listType == 'vp') {
            $('#ddlVpCounties').trigger("chosen:updated");
        }
        else {
            $('#ddlStateCounties').trigger("chosen:updated");
        } 
    });
}

function ListLocalCounties() {

    var lu = $('#hiddenLocalNumber').val();
    var jParms = { action: "list-local-counties", lu: lu };
    var lst = $.getJSON('DataIO.ashx', jParms, "JSON");
    var anchor = 'http://www.ibew.org/IBEW/directory/maps/LU ' + lu; // 1-Inside-MO.pdf';
    var bylaws = '';
    var map = '';
    lst.done(function (jArray) {
        var wrk = "";
        if (jArray.length > 0) {
            var dist = jArray[0].District;
            if (parseInt(dist) == 1) {
                $('thead th.county-hdr').text('Census Division');
            }
            else {
                $('thead th.county-hdr').text('County Name');
            }
            for (var ii = 0; ii < jArray.length; ii++) {
                wrk += '<tr>';
                var o = jArray[ii];
                map = o.StateProvince;
                //                if (o.jurisdiction == "I") {
                //                    map += '-Inside.gif';
                //                }
                //                else {
                //                    map += '-Outside.gif';
                //                }
                wrk += '<td class="StateImageMap hand" filter="' + o.jurisdiction + '" map="' + map + '">' + o.CountyName + '</td>';
                wrk += '<td>' + o.Population + '</td>';
                wrk += '<td>' + o.LandArea + '</td>';
                if (o.jurisdiction == "I") {
                    bylaws = anchor + '-Inside-' + o.StateProvince + '.pdf';
                }
                else {
                    bylaws = anchor + '-Outside-' + o.StateProvince + '.pdf';
                }
                //wrk += '<td><a href="' + bylaws + '" target="_blank" >' + o.Percentage + '</a></td>';
                wrk += '<td>' + o.Percentage + '</td>';
                if (o.jurisdiction == "I") {
                    wrk += '<td>Inside</td>';
                }
                else {
                    wrk += '<td>Outside</td>';
                }
                wrk += '</tr>';
            }
        }
        $('tbody.local-county-list').html(wrk);

//        $('td.StateImageMap').click(function (e) {
//            var state = $(this).attr('map');
//            var filter = $(this).attr('filter');
//            if (filter == "I") {
//                filter = 'Inside';
//            }
//            else {
//                filter = 'Outside';
//            }
//            if (filter == "Inside") {
//                $('#hiddenMapImageUrl').val('http://www.ibew.org/IBEW/directory/images3/' + state + '-' + filter + '.gif');
//                // $('#hiddenMapPdfUrl').val('http://www.ibew.org/IBEW/directory/Maps/' + state + '-' + filter + '.pdf');
//                $('#hiddenMapPdfUrl').val('');
//                $('#hiddenMapMode').val('static');
//                $('#staticHdr').html('<h4>' + filter + ' Jurisdiction Map for ' + state + '</h4>');
//                $('#lusTabs a[href="#maps"]').tab('show');
//            }
//        });

    });

    lst.fail(function () {
    
    });

    lst.always(function () {

    });

}

function CountyListEvents(ddlName) {
    // on change...
    $('#' + ddlName).chosen().change(function () {
        selectedCounty = $('#' + ddlName).val();
    });
}

function LoadCountyResultsTable(tab) {
    var iLU = "";
    var oLU = "";
    var wrk = "";
    var jParms = { action: "county-locals", county: selectedCounty, canada: OhCanada };
    var tbl = $.getJSON('DataIO.ashx', jParms, "JSON");
    $('div.' + tab + '-county-results h5').html('Inside/Outside Local Unions Representing <b>' + selectedCounty + '</b>');
    tbl.done(function (jArray) {
        if (jArray.length > 0) {
            $('div.' + tab + '-population').text('Population: ' + jArray[0].Population);
            $('div.' + tab + '-landarea').text('Land Area: ' + jArray[0].LandArea);
            for (var ii = 0; ii < jArray.length; ii++) {
                wrk += '<tr>';
                var o = jArray[ii];
                if (iLU != o.InsideLocal) {     // new data for inside
                    wrk += '<td><a href="#" class="show-county-local" luid="' + o.iLocalID + '">' + o.InsideLocal + '</a></td>';
                    //wrk += '<td><a href="' + o.InsideBylawsLink + '" target="_blank">' + o.InsidePercentage + '</a></td>';
                    wrk += '<td>' + o.InsidePercentage + '</td>';
                    iLU = o.InsideLocal;
                }
                else {
                    wrk += '<td></td><td></td>';
                }
                if (oLU != o.OutsideLocal) {     // new data for inside
                    wrk += '<td><a href="#" class="show-county-local" luid="' + o.oLocalID + '">' + o.OutsideLocal + '</a></td>';
                    //wrk += '<td><a href="' + o.OutsideBylawsLink + '" target="_blank">' + o.OutsidePercentage + '</td>';
                    wrk += '<td>' + o.OutsidePercentage + '</td>';
                    oLU = o.OutsideLocal;
                }
                else {
                    wrk += '<td></td><td></td>';
                }
                wrk += '</tr>';
            }
        }
        else {
            wrk = "<tr><td colspan='4'>No Locals Found for this County/Census area</td></tr>";
        }
        $('tbody.' + tab + '-county-locals').html(wrk);

        $('a.show-county-local').click(function (e) {
            $('#hiddenLocalID').val($(this).attr('luid'));
            $('#hiddenLocalNumber').val($(this).text());
            $('#hiddenMapMode').val('LU');
            $('#lusTabs a[href="#results"]').tab('show');
            e.preventDefault();
        });

    });
}




//  wire up button events..........................................................................
$(function () {
    //  VP Panel.................................
    $('button.vp-counties').click(function (e) {
        $('div.vp-local-list').fadeOut();
        $('div.vp-county-results').fadeIn();
        LoadCountyResultsTable('vp');
        e.preventDefault();
    });
    $('button.vp-view-locals').click(function (e) {
        $('div.vp-county-results').fadeOut();
        $('div.vp-local-list').slideDown(800);
        e.preventDefault();
    });
    //  State Panel..............................
    $('button.state-counties').click(function (e) {
        $('div.state-local-list').fadeOut();
        $('div.state-county-results').fadeIn();
        LoadCountyResultsTable('state');
        e.preventDefault();
    });
    $('button.state-view-locals').click(function (e) {
        $('div.state-county-results').fadeOut();
        $('div.state-local-list').slideDown(800);
        e.preventDefault();
    });
    //  Local Panel..............................
    $('#luCountyJurisdiction').click(function (e) {
        var info = $(this).attr('info');
        if (info == "show") {
            $('div.local-info').hide();
            $(this).attr('info', 'hide');
            $(this).text("Show Local Information");
            $('div.county-jurisdiction').show();
            ListLocalCounties();
        }
        else {
            $('div.local-info').show();
            $(this).attr('info', 'show');
            $(this).text("Show County Jurisdictions");
            $('div.county-jurisdiction').hide();
        }
        e.preventDefault();
    });

});
