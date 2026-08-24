//
//  <h3 id='vpHeaderTitle'>&nbsp;</h3>
//  <div id="vpContent"></div>
//

var IVP;

function vpFormatInfo() {
    if ($('#hiddenVpDistrict').val() != "" && $('#hiddenVpDistrict').val() != "0") {
        var n = parseInt($('#hiddenVpDistrict').val());
        var o = IVP[n - 1];
        $('div.vp-section').show();
        $('h3.vpHeaderTitle').text('IVP ' + o.DistrictName + ' (' + $('#hiddenFilterOption').val() + ')');
        $('img.vpImage').prop('src', 'images/VP/' + o.Picture);
        $('img.vpImage').prop('atl', 'IVP ' + o.Title);
        $('label.vp_name').text(o.Fname + ' ' + o.MI + ' ' + o.Lname);
        $('label.vp_phone').text(o.Phone);
        $('label.vp_fax').text(o.Fax);
        $('span.vp_addr1').text(o.Address1);
        $('span.vp_addr2').text(o.Address2);
        $('span.vp_city_state_zip').text(o.City + ', ' + o.State + ' ' + o.Zip);
        $('a.vp_email').prop('href', 'mailto:' + o.Email);
        $('a.vp_website').prop('href', 'http://' + o.Website);
    }
    else {
        if ($('#hiddenMapMode').val() === 'County') {
            $('#lusTabs a[href="#search"]').tab('show');
        }
    }
}





