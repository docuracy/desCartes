from flask import Flask, request, jsonify
app = Flask(__name__)

@app.route("/", methods=['GET', 'POST'])
def hello():
    if request.method == 'GET':
        bounds = request.get_json().get('bounds')
        if bounds:
            return jsonify({"bounds": bounds})
        else:
            return jsonify({"message": "No bounds found in the request."})
    else:
        return jsonify({"message": "POST desCartes!"})

if __name__ == "__main__":
    app.run(host='0.0.0.0')
