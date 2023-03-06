//
// @author: Stephen Gadd, Docuracy Ltd, UK
//

// Maximum allowed area of the selection rectangle in square kilometers
var max_allowed_area = 10;

var getViewID = true;
function viewID(){
	if (getViewID === true) {
		var dt = new Date().getTime();
	    getViewID = 'xxxxxxxx-xxxx-xxxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
	        var r = (dt + Math.random()*16)%16 | 0;
	        dt = Math.floor(dt/16);
	        return (c=='x' ? r :(r&0x3|0x8)).toString(16);
	    });
	}
	return getViewID
}

function spinner(toggle = true) {
    $(".spinner div").toggle((!typeof toggle === "string" || toggle === "") && toggle);
    if (typeof toggle === "string") $("#spinner-text").text(toggle);
    $(".spinner-overlay").toggle(typeof toggle === "string" || toggle);
    $(".spinner-overlay span.close-button").toggle(typeof toggle === "string" && toggle !== "");
}

function updateButton(rect) {
    var bounds = rect.getBounds();
    var area = calculateRectangleArea(bounds);
    $("#send").prop("disabled", area > max_allowed_area);
    $("#send").text((area > max_allowed_area ? "Area Too Large" : "Start Processing") + " [" + area + " km²]");
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

    response.result_images.forEach(function(image, i) {
        var figure = $("<div>").addClass("figure").appendTo(thumbnailsContainer);
        var thumbnail = $("<img>").addClass("thumbnail").attr("src", "data:image/jpeg;base64," + image.thumbnail).appendTo(figure);
        var label = $("<div>").addClass("thumbnail-label").text((i + 1) + '. ' + image.label).appendTo(figure);

        thumbnail.click(function() {
            var overlay = $("<div>").addClass("overlay").appendTo("body");
            var fullscreenImage = $("<img>").addClass("fullscreen-image").attr("src", "../../git/" + image.url).appendTo("body");
            var closeButton = $("<div>").addClass("close-button").text("X").appendTo("body");
            closeButton.click(function() {
                fullscreenImage.remove();
                closeButton.remove();
                overlay.remove();
            });
        });
    });

    if (response.message !== '') {
		$("<span class='comment'>" + response.message + "</span>").appendTo(thumbnailsContainer);
    }
	$("<span class='comment'>To improve results, you may need to adjust the parameters before processing.</span>").appendTo(thumbnailsContainer);
    var downloadButton = $("<button class='download'>").text("Download GeoPackage").appendTo(thumbnailsContainer);
	downloadButton.click(function() {
	    var link = document.createElement('a');
	    link.href = '../../git/' + response.GeoPackage;
	    link.download = 'desCartes.gpkg'; 
	    document.body.appendChild(link);
		console.log(link)
	    link.click();
	    document.body.removeChild(link);
	});
	var zipButton = $("<button class='download'>").text("Download Zipped Images").appendTo(thumbnailsContainer);
	zipButton.click(function() {
	    var link = document.createElement('a');
		var directory = response.GeoPackage.substring(0, response.GeoPackage.lastIndexOf('/') + 1);
	    link.href = '../../git/' + directory + '/images.zip';
	    link.download = 'desCartes_images.zip';
	    document.body.appendChild(link);
	    link.click();
	    document.body.removeChild(link);
	});


}

$(document).ready(function() {
    spinner(true);
    $(".spinner-overlay button, .spinner-overlay span.close-button").click(function() {
        spinner(false);
    });

    var map = L.map('map');

    $("#send").click(function() {
        spinner("");
        var formData = new FormData($('#road-parameters')[0]);
        var bounds = rect.getBounds();
		formData.append('bounds', bounds.getSouthWest().lng + "," + bounds.getSouthWest().lat + "," + bounds.getNorthEast().lng + "," + bounds.getNorthEast().lat);
		formData.append('viewID', viewID());
		formData.append('colours', JSON.stringify(defaultValues[selectedIndex].colours));
		$.ajax({
            type: "POST",
            timeout: 60000, // set a 1-minute timeout in milliseconds
			data: formData,
		    contentType: false,
		    processData: false,
            url: "https://descartes.viaeregiae.org/",
            success: function(response) {
                if (response && response.result_images && response.result_images.length > 0) {
                    showCandidateLines(response)
                } else {
                    spinner("Sorry, something went wrong. The server returned an unexpected response. [" + response.error + "]");
                }
            },
            error: function(jqXHR, textStatus, errorThrown) {
                if (textStatus === 'timeout') {
                    spinner("Sorry, something went wrong. The server failed to respond within the allowed time.");
                } else {
                    var response = jqXHR.responseJSON;
					report = typeof response === 'undefined' ? "" : " Error " + response.error.code + ": " + response.error.message;
                    spinner("Sorry, something went wrong." + report);
                }
            }
        });
    });

	$('#donate').click(function() {
	  window.open('https://ko-fi.com/docuracy', '_blank');
	});

    $("#toggleForm").click(function() {
        $("#road-parameters").toggle();
        $(this).text($(this).text() == "Adjust Parameters" ? "Hide Parameters" : "Adjust Parameters");
    }).click();

    $("#road-parameters label").each(function() {
        $(this).append("<sup class='tooltip-mark'>?</sup>");
    });

    for (i = 1; i <= 11; i += 2) {
        $('#blur_size').append($("<option>", {
            value: i,
            text: i
        }));
    }
    for (i = 0; i <= 254; i++) {
        $('#binarization_threshold').append($("<option>", {
            value: i,
            text: i
        }));
    }
    for (i = 0; i <= 30; i++) {
        $('#gap_close').append($("<option>", {
            value: i,
            text: i
        }));
    }

	let defaultValues = {};
  	let selectedIndex = 0;
	let tiles = false;
	let rect = false;

	$.getJSON('./data/map_defaults.json', function(data) {
	    defaultValues = data;
	    populateDropdown();
	    populateForm();
	});
	
	$('#custom-url').on("blur", function() {
	    const newUrl = this.value;
		tiles = L.tileLayer(newUrl, {
	        maxZoom: 18
	    }).addTo(map);
	});
	
	$("#shape_filter").change(function() {
		$("#shape_filter_parameters").toggle($("#shape_filter").val() == "True");
	})

	function populateDropdown() { // with descriptions and urls from the JSON
	    const dropdown = $('#default_values_dropdown');
	    for (let i = 0; i < defaultValues.length; i++) {
	      dropdown.append(`<option value="${i}">${defaultValues[i].description}</option>`);
	    }
	    dropdown.change(function() {
		  getViewID = true;
	      selectedIndex = parseInt(dropdown.val());
	      populateForm();
		  $('#custom-inputs').toggle(selectedIndex == defaultValues.length - 1);
	    });
	}
  
	function populateForm() { // with the default values from the JSON
	    const defaults = defaultValues[selectedIndex];
		max_allowed_area = defaults.max_allowed_area;

		const inputs = ['blur_size', 'binarization_threshold', 'MAX_ROAD_WIDTH', 'MIN_ROAD_WIDTH', 'convexity_min', 'min_size_factor', 'inflation_factor', 'gap_close', 'templating', 'shape_filter', 'maximum_tree_density', 'url', 'zoom', 'modern_roads']
	    for (let property of inputs) {
		  $(`#${property}`).val(defaults[property]).prop('disabled', !defaults.hasOwnProperty(property))};

		$("#shape_filter_parameters").toggle($("#shape_filter").val() == "True");
	
	    if (rect !== false) {
			rect.remove();
		}
	    rect = L.rectangle(defaults.start_extent, {
	        color: "#ff7800",
	        weight: 1
	    }).addTo(map);
	    var bounds = rect.getBounds();
	    map.fitBounds(bounds);
	    rect.editing.enable();
	    $("#instructions span#max_allowed_area").text(max_allowed_area);
	    updateButton(rect);
	    rect.on('edit', function() {
			getViewID = true;
	        updateButton(rect);
	    });
	
	    if (tiles !== false) {
			tiles.remove();
		}
		tiles = L.tileLayer(defaults.url, {
	        attribution: defaults.attribution,
	        maxZoom: 18
	    }).addTo(map);
	}

});