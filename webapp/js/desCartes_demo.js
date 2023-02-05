//
// @author: Stephen Gadd, Docuracy Ltd, UK
//

$(document).ready(function() {
    var map = L.map('map').setView([51.507505467209405, -2.3340990998876934], 15);
    L.tileLayer('https://api.maptiler.com/tiles/uk-osgb10k1888/{z}/{x}/{y}.jpg?key=ySlCyGP2kmmfm9Dgtiqj', {
        attribution: 'Map &copy; National Library of Scotland',
        maxZoom: 18
    }).addTo(map);
    var rect = L.rectangle([
        [51.50083068350566, -2.351390649563276],
        [51.51321498717301, -2.3244272838851536]
    ], {
        color: "#ff7800",
        weight: 1
    }).addTo(map);
    rect.editing.enable();
    $("#send").click(function() {
        var bounds = rect.getBounds();
        console.log(bounds)
        $.ajax({
		  type: "GET",
		  url: "https://descartes.viaeregiae.org/?bounds=" + encodeURIComponent(bounds.getSouthWest().lng) + "," + encodeURIComponent(bounds.getSouthWest().lat) + "," + encodeURIComponent(bounds.getNorthEast().lng) + "," + encodeURIComponent(bounds.getNorthEast().lat),
		  success: function(response) {
		    var image = new Image();
		    image.src = "data:image/jpeg;base64," + response.base64_image;
			var modalDialog = $("<div>").addClass("modal-dialog").appendTo("body");
			modalDialog.append('<div id="imageModal"></div>');
			modalDialog.modal({
				fadeDuration: 100,
			});
		    var imageMap = L.map("imageModal").setView([51.507505467209405, -2.3340990998876934], 15);
		    L.tileLayer(image.src, {
		      	maxZoom: 18
		    }).addTo(imageMap);
			$(".modal-dialog").click(function () {
				$(this).modal("hide");
			});
		  }
		});
    });
});