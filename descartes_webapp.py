from flask import Flask, request, jsonify
app = Flask(__name__)

@app.route("/")
def hello():
    msg = request.get_json().get('msg')
    if msg:
        return jsonify({"message": msg})
    else:
        return jsonify({"message": "desCartes!"})

if __name__ == "__main__":
    app.run(host='0.0.0.0')
