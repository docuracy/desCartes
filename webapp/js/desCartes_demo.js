//
// @author: Stephen Gadd, Docuracy Ltd, UK
//

// Maximum allowed area of the selection rectangle in square kilometers
const MAX_ALLOWED_AREA = 10;

function spinner(toggle = true) {
    $(".spinner div").toggle((!typeof toggle === "string" || toggle === "") && toggle);
    if (typeof toggle === "string") $("#spinner-text").text(toggle);
    $(".spinner-overlay").toggle(typeof toggle === "string" || toggle);
}

function updateButton(rect) {
    var bounds = rect.getBounds();
    var area = calculateRectangleArea(bounds);
    $("#send").prop("disabled", area > MAX_ALLOWED_AREA);
    $("#send").text((area > MAX_ALLOWED_AREA ? "Area Too Large" : "Start Processing") + " [" + area + " km²]");
}

// Function to calculate the area of a rectangle in square kilometers
function calculateRectangleArea(bounds) {
    // Earth's radius in kilometers
    const EARTH_RADIUS = 6371;
    var lat1Rad = Math.min(bounds.getNorth(), bounds.getSouth()) * (Math.PI / 180);
    var lat2Rad = Math.max(bounds.getNorth(), bounds.getSouth()) * (Math.PI / 180);
    var lng1Rad = Math.min(bounds.getWest(), bounds.getEast()) * (Math.PI / 180);
    var lng2Rad = Math.max(bounds.getWest(), bounds.getEast()) * (Math.PI / 180);

    var deltaLat = lat2Rad - lat1Rad;
    var deltaLng = lng2Rad - lng1Rad;

    var a = Math.sin(deltaLat / 2) * Math.sin(deltaLat / 2) +
        Math.cos(lat1Rad) * Math.cos(lat2Rad) *
        Math.sin(deltaLng / 2) * Math.sin(deltaLng / 2);
    var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    var distance = EARTH_RADIUS * c;

    var area = distance * distance * Math.PI;
    return area.toFixed(1);
}

function showCandidateLines(response) {
    spinner(false);
	var width = Math.round($(window).width() * .9);
	var height = Math.round($(window).height() * .9);
    var modalDialog = $("<div title='Candidate Road Lines (close this dialog to continue processing)'>").addClass("modal-dialog").appendTo("body");
    modalDialog.dialog({
        width: width,
        height: height,
        modal: true,
        close: function() {
            spinner("Further steps are not yet part of this demonstration.");
            modalDialog.remove();
        }
    });
    var imageMap = L.map(modalDialog[0], {
		minZoom: 0,
	    maxZoom: 10,
        crs: L.CRS.Simple
    });
    var image = new Image();
    image.src = "data:image/jpeg;base64," + response.base64_image;
    image.onload = function() {
        var bounds = [
            [0, 0],
            [image.height / 1.7, image.width / 1.7]
        ];
        var imageOverlay = L.imageOverlay(image.src, bounds).addTo(imageMap);
        imageMap.fitBounds(bounds);
    }
}

$(document).ready(function() {
    spinner(true);
    $(".spinner-overlay button").click(function() {
        spinner(false);
    });

    var map = L.map('map');

    var rect = L.rectangle([
        [51.50083068350566, -2.351390649563276],
        [51.51321498717301, -2.3244272838851536]
    ], {
        color: "#ff7800",
        weight: 1
    }).addTo(map);
    var bounds = rect.getBounds();
    map.fitBounds(bounds);
    rect.editing.enable();
    $("#instructions span").text(function(i, text) {
        return text.replace("***", MAX_ALLOWED_AREA);
    });
    updateButton(rect);

    L.tileLayer('https://api.maptiler.com/tiles/uk-osgb10k1888/{z}/{x}/{y}.jpg?key=ySlCyGP2kmmfm9Dgtiqj', {
        attribution: 'Map &copy; National Library of Scotland',
        maxZoom: 18
    }).addTo(map);

    // Event listener to monitor changes in rectangle
    rect.on('edit', function() {
        updateButton(rect);
    });

    $("#send").click(function() {
        spinner("");
        var bounds = rect.getBounds();
        $.ajax({
            type: "GET",
            url: "https://descartes.viaeregiae.org/?bounds=" + encodeURIComponent(bounds.getSouthWest().lng) + "," + encodeURIComponent(bounds.getSouthWest().lat) + "," + encodeURIComponent(bounds.getNorthEast().lng) + "," + encodeURIComponent(bounds.getNorthEast().lat),
            success: function(response) {
                showCandidateLines(response)
            }


        });
    });
});