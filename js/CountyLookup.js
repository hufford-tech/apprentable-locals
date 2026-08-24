/// <reference path="jquery-1.10.2.min.js" />
/// <reference path="bootstrap.min.js" />
/// <reference path="chosen.jquery.min.js" />

function SearchCountyList() {

    var txt = $('#tbxCountyName').val();
    var jParms = { action: 'list-counties', search: txt };
    var counties = $.getJSON("DataIO.ashx", jParms, "JSON");

    counties.done(function (jArray) {
        if (jArray.length > 0) {
            var wrk = '';
            $.each(jArray, function (idx, o) {
                wrk += CountyRow(o);
            });
            $('#ListCountiesHere').html(wrk);

            $('a.map-county').click(function (e) {
                e.preventDefault();
                var county = $(this).text();
                var state = $(this).attr("state");
                $('#staticMaps').html('');
                $('#divStatic').hide();
                $('#staticPdfLink').hide();
                $('#hiddenCounty').val(county);
                $('#hiddenMapMode').val('County');
                $('#hiddenStateProvince').val(state)
                $('#lusTabs a[href="#maps"]').tab('show');
                //$('#map-canvas').show();

                //changeMapCountyLayer(county);
                //google.maps.event.trigger(map, 'resize');
            });
        }
        else {
            alterify.error("No Results Found");
        }
    });

}

function CountyRow(o) {
    var wrk = '<tr><td>' + o.County + '</td><td>' + o.State + '</td><td><a href="" class="map-county" state="' + o.State + '" data-dismiss="modal">' + o.mapField + '</td></tr>';
    return wrk;
}