from flask import Flask, request, jsonify
app = Flask(__name__)

@app.route("/", methods=['GET', 'POST'])
def hello():
    if request.method == 'GET':
        bounds = request.args.get('bounds')
        if bounds:
            return jsonify({"bounds": bounds})
        else:
            return jsonify({"message": "No bounds found in the request."})
    else:
        # POST requests are not properly handled by nginx/Apache on IONOS system
        msg = request.get_json().get('msg')
        if msg:
            return jsonify({"message": msg})
        else:
            return jsonify({"message": "POST desCartes!"})

if __name__ == "__main__":
    app.run(host='0.0.0.0')

