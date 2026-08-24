/// <reference path="jquery-1.10.2.js" />


function initialize() {
    map = new google.maps.Map(document.getElementById('map-canvas'), {
        center: new google.maps.LatLng(39.38443652964032, -96.44376484375006),
        zoom: 3,
        mapTypeId: google.maps.MapTypeId.ROADMAP
    });

    //LOCAL UNIONS
    luLayer = new google.maps.FusionTablesLayer({
        //map:map,
        query: {
            select: "'col4'",
            from: '1oecBm-0r2cOD-EpxtIpcVVzZa7DYK-4x11HKDmld',      //'1C5O-c4M7rMu5ozZA7rrVuxdv0Fp6hVvSANpmIgk', 
        },
        styleId: 2,
        templateId: 2
    });

    layerDistrict = new google.maps.FusionTablesLayer({
        query: {
            select: "'col3>>1'",
            from: '1PQ9WNSu4P0KytykiznsaATWvvEbIsGIHwd8cJII'
        },
        styleId: 2,
        templateId: 2
    });

    //toggleLayers('0');

    //changeMapLULayer(5);

}

/********  map functions  **********************
***********************************************/
function toggleLayers(activeLayer) {
    luLayer.setMap(null);
    layerDistrict.setMap(null);
    //layerl2.setMap(null);
    //layerl3.setMap(null);

    switch (activeLayer) {
        case '0':
            //don't do anything
            break;
        case 'lu':
            luLayer.setMap(map);
            break;
        case 'd':
            layerDistrict.setMap(map);
            break;
        default:
    }
}

function changeMapCountyLayer(val, st) {
    //alert(padLeft(val, 4, '0'));
    //alert('lu = ' + val);
    toggleLayers('lu');

    luLayer.setOptions({
        query: {
            select: "'col4'",
            from: '1oecBm-0r2cOD-EpxtIpcVVzZa7DYK-4x11HKDmld', //'1F9pprTqksMpx3uzdqsK1wqPdUDwidP37MacmmzQ',
            where: "'StCounty' CONTAINS IGNORING CASE '" + val + "'"
        }
    });
  

    //  set map zoom and center
//    var zoom;
//    if (map.getZoom() == 3) {
//        map.setZoom(luZoom);
//        zoom = luZoom;
//    }
//    else {
//        luZoom = map.getZoom();
//        zoom = luZoom;
//    }

    var center;
    fnSetMapOptions(st);
    $('#map-control-buttons').hide();

//    center = new google.maps.LatLng(39.38443652964032, -96.44376484375006);
//    zoom = 3;
//    map.setCenter(center);
//    map.setZoom(zoom);

}

function changeMapLULayer(val, ioval) {
    //alert(padLeft(val, 4, '0'));
    //alert('lu = ' + val);
    toggleLayers('lu');
    if (ioval == undefined) {
        luLayer.setOptions({
            query: {
                select: "'col4'",
                from: '1oecBm-0r2cOD-EpxtIpcVVzZa7DYK-4x11HKDmld', //'1F9pprTqksMpx3uzdqsK1wqPdUDwidP37MacmmzQ',
                where: "'lu' = " + val + " and 'inside_outside' = 'I'"
            }
        });
    }
    else {
        luLayer.setOptions({
            query: {
                select: "'col4'",
                from: '1oecBm-0r2cOD-EpxtIpcVVzZa7DYK-4x11HKDmld', //'1F9pprTqksMpx3uzdqsK1wqPdUDwidP37MacmmzQ',
                where: "'lu' = " + val + " and 'inside_outside' = '" + ioval + "'"
            }
        });
    }

    //  set map zoom and center
    var zoom;
    if (map.getZoom() == 3) {
        map.setZoom(luZoom);
        zoom = luZoom;
    }
    else {
        luZoom = map.getZoom();
        zoom = luZoom;
    }
    
    var center;
    //you can go get the details of the local union here via json and return them to the center and zoom variables
    // this will pan and zoom the map to that local...

    //var luAjaxCall = $.getJSON('handlers/luDetail.ashx', { lu: val }, "JSON");
    var luAjaxCall = $.getJSON('DataIO.ashx', { action: "local-lat-lon", lu: val }, "JSON");

    luAjaxCall.done(function (jdata) {
        var data = jdata[0];
        center = new google.maps.LatLng(data.Latitude, data.Longitude);
        // zoom = 8;
    });

    luAjaxCall.fail(function () {
        //run fail alert here
        //alertify.log("BREAK");
        center = new google.maps.LatLng(39.38443652964032, -96.44376484375006);
        zoom = 3;
    });

    luAjaxCall.always(function () {
        map.setCenter(center);
        map.setZoom(zoom);
        //alertify.log(luZoom + '/' + zoom);
    });

    //layerl2.setMap(null);
    //luLayer.setMap(map);
}

function changeMapStateLayer(val, ioval) {
    //alert(padLeft(val, 4, '0'));
    //alert('lu = ' + val);
    toggleLayers('lu');
    //if (ioval == undefined) {
    luLayer.setOptions({
        query: {
            select: "'col4'",
            from: '1oecBm-0r2cOD-EpxtIpcVVzZa7DYK-4x11HKDmld', //'1F9pprTqksMpx3uzdqsK1wqPdUDwidP37MacmmzQ',
            where: "'StAbbr' = '" + val + "'" // + " and 'inside_outside' = 'I'"
        }
    });
    //}
    //else {
//        luLayer.setOptions({
//            query: {
//                select: "'col4'",
//                from: '1oecBm-0r2cOD-EpxtIpcVVzZa7DYK-4x11HKDmld', //'1F9pprTqksMpx3uzdqsK1wqPdUDwidP37MacmmzQ',
//                where: "'lu' = " + val + " and 'inside_outside' = '" + ioval + "'"
//            }
//        });
//    }

    //  set map zoom and center
//    var zoom;
//    if (map.getZoom() == 3) {
//        map.setZoom(luZoom);
//        zoom = luZoom;
//    }
//    else {
//        luZoom = map.getZoom();
//        zoom = luZoom;
//    }
    
    var center;
    //you can go get the details of the local union here via json and return them to the center and zoom variables
    // this will pan and zoom the map to that local...

    //var luAjaxCall = $.getJSON('handlers/luDetail.ashx', { lu: val }, "JSON");
    fnSetMapOptions(val);
    $('#map-control-buttons').hide();
//    var luAjaxCall = $.getJSON('DataIO.ashx', { action: "local-lat-lon", lu: val }, "JSON");

//    luAjaxCall.done(function (jdata) {
//        var data = jdata[0];
//        center = new google.maps.LatLng(data.Latitude, data.Longitude);
//        // zoom = 8;
//    });

//    luAjaxCall.fail(function () {
//        //run fail alert here
//        //alertify.log("BREAK");
//        center = new google.maps.LatLng(39.38443652964032, -96.44376484375006);
//        zoom = 3;
//    });

//    luAjaxCall.always(function () {
//        map.setCenter(center);
//        map.setZoom(zoom);
//        //alertify.log(luZoom + '/' + zoom);
//    });

    //layerl2.setMap(null);
    //luLayer.setMap(map);
}



function changeMapl0(ddlval) {
    //removeMarkers();
    toggleLayers('d');
    //clearFilters('dist');
    fnSetMapOptions(ddlval);
    //fnSetLogLocation('dist', ddlval);
    //$("#btnShowDetails").val("Dist Details");
    //getChildrenList('district', ddlval);

    layerDistrict.setOptions({
        query: {
            select: "'col3>>1'",
            from: '1PQ9WNSu4P0KytykiznsaATWvvEbIsGIHwd8cJII',
            where: "'District' = '" + ddlval + "'"
        }
    });
}

var luZoom = 8;

function fnSetMapOptions(locKey, zoomlevel) {
    var lat;
    var lon;
    var zoom;
    var center;
    //alertify.log(zoomlevel);

    if (locKey == -1) {
        center = new google.maps.LatLng(39.38443652964032, -96.44376484375006);
        zoom = $.isNumeric(zoomlevel) ? zoomlevel : 3;
        luZoom = zoom;
        map.setCenter(center);
        map.setZoom(zoom);
    }
    else {

        var o = $.getJSON('handlers/luMaps.ashx', { Location: locKey }, "JSON");

        o.done(function (data) {
            center = new google.maps.LatLng(data.lat, data.lon);
            zoom = data.ZoomLevel;
            luZoom = zoom;
        });

        o.fail(function () {
            //run fail alert here
            center = new google.maps.LatLng(39.38443652964032, -96.44376484375006);
            zoom = 3;
            luZoom = zoom;
        });

        o.always(function () {
            map.setCenter(center);
            map.setZoom(zoom);
        });

        //layerl2.setMap(null);
        //layerDistrict.setMap(map); 

    }
}
//
//  Local Union Map Controls..................................................................
//
function BuildMapControls() {
    $('#map-control-buttons').html('');
    var lu = gLocal;  // $('#hiddenLocalNumber').val();
    var jParms = { action: "map-types", lu: lu };
    var mc = $.getJSON('DataIO.ashx', jParms, "JSON");

    mc.done( function( jArray) {
        if (jArray.length > 0) {
            var wrk = '<div class="btn-group">';
            $.each(jArray, function( idx, oItem) {
                if (idx == 0) {
                    wrk += '<button class="btn btn-primary map-btn" ';
                    changeMapLULayer(lu, oItem.inside_outside);
                    google.maps.event.trigger(map, 'resize');
                }
                else {
                    wrk += '<button class="btn btn-info map-btn" ';
                }
                wrk += 'lu="' + lu + '" ';
                switch (oItem.inside_outside) {
                    case "I":
                        wrk += 'map="I">Inside</button>';
                        break;
                    case "O":
                        wrk += 'map="O">Outside</button>';
                        break;
                    case "CI":
                        wrk += 'map="CI">Outside Commerical/Industrial</button>';
                        break;
                    case "LC":
                        wrk += 'map="LC">Outside Line Construction</button>';
                        break;
                }
            });
            wrk += '</div>';
            $('#map-control-buttons').html(wrk);

            $('button.map-btn').click(function(e) {
                $('button.map-btn').removeClass('btn-primary').removeClass('btn-info').addClass('btn-info');
                var lu = $(this).attr("lu");
                var maptype = $(this).attr("map");
                $(this).removeClass('btn-info').addClass('btn-primary');
                changeMapLULayer(lu, maptype);
                google.maps.event.trigger(map, 'resize');
                e.preventDefault();
            });
            
        }
    });

}



