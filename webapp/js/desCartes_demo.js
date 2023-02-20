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
    var modalDialog = $("<div title='Click image to enlarge it, or Download GeoPackage of extracted road vectors.'>").addClass("modal-dialog").appendTo("body");
    modalDialog.dialog({
        width: width,
        height: height,
        modal: true,
        close: function() {
            /*spinner("Further steps are not yet part of this demonstration.");*/
            modalDialog.remove();
        }
    });

    var thumbnailsContainer = $("<div>").addClass("thumbnails-container").appendTo(modalDialog);

    response.base64_images.forEach(function(image, i) {
        var figure = $("<div>").addClass("figure").appendTo(thumbnailsContainer);
        var thumbnail = $("<img>").addClass("thumbnail").attr("src", "data:image/jpeg;base64," + image.image).appendTo(figure);
        var label = $("<div>").addClass("thumbnail-label").text((i + 1) + '. ' + image.label).appendTo(figure);

        thumbnail.click(function() {
            var overlay = $("<div>").addClass("overlay").appendTo("body");
            var fullscreenImage = $("<img>").addClass("fullscreen-image").attr("src", "data:image/jpeg;base64," + image.image).appendTo("body");
            var closeButton = $("<div>").addClass("close-button").text("X").appendTo("body");
            closeButton.click(function() {
                fullscreenImage.remove();
                closeButton.remove();
                overlay.remove();
            });
        });
    });

    $("<span class='comment'>To improve results, you may need to adjust the parameters before processing.</span>").appendTo(thumbnailsContainer);
    var downloadButton = $("<button class='download'>").text("Download GeoPackage").appendTo(thumbnailsContainer);
    downloadButton.click(function() {
        var binary = atob(response.GeoPackage.gpkg);
        var byteArray = new Uint8Array(binary.length);
        for (var i = 0; i < binary.length; i++) {
            byteArray[i] = binary.charCodeAt(i);
        }
        var blob = new Blob([byteArray], {
            type: "application/x-sqlite3"
        });
        var downloadLink = document.createElement("a");
        downloadLink.href = URL.createObjectURL(blob);
        downloadLink.download = "desCartes.gpkg";
        document.body.appendChild(downloadLink);
        downloadLink.click();
        document.body.removeChild(downloadLink);
    })

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
        var formData = $("#road-parameters").serialize();
        $.ajax({
            type: "GET",
            timeout: 60000, // set a 1-minute timeout in milliseconds
            dataType: 'json',
            url: "https://descartes.viaeregiae.org/?bounds=" + encodeURIComponent(bounds.getSouthWest().lng) + "," + encodeURIComponent(bounds.getSouthWest().lat) + "," + encodeURIComponent(bounds.getNorthEast().lng) + "," + encodeURIComponent(bounds.getNorthEast().lat) + "&" + formData,
            success: function(response) {
                if (response && response.base64_images && response.base64_images.length > 0) {
                    showCandidateLines(response)
                } else {
                    spinner("Sorry, something went wrong. The server returned an unexpected response.");
                }
            },
            error: function(jqXHR, textStatus, errorThrown) {
                if (textStatus === 'timeout') {
                    spinner("Sorry, something went wrong. The server failed to respond within the allowed time.");
                } else {
                    var response = jqXHR.responseJSON;
                    spinner("Sorry, something went wrong." + "Error " + response.error.code + ": " + response.error.message);
                }
            }
        });
    });

    $("#toggleForm").click(function() {
        $("#road-parameters").toggle();
        $(this).text($(this).text() == "Adjust Parameters" ? "Hide Parameters" : "Adjust Parameters");
    }).click();

    for (i = 1; i <= 11; i += 2) {
        $('#blur_size').append($("<option>", {
            value: i,
            text: i,
            selected: (i == 3)
        }));
    }
    for (i = 0; i <= 254; i++) {
        $('#binarization_threshold').append($("<option>", {
            value: i,
            text: i,
            selected: (i == 210)
        }));
    }
    for (i = 0; i <= 30; i++) {
        $('#gap_close').append($("<option>", {
            value: i,
            text: i,
            selected: (i == 20)
        }));
    }
    $("#road-parameters label").each(function() {
        $(this).append("<sup class='tooltip-mark'>?</sup>");
    });
});