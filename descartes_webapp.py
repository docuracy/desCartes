from flask import Flask, request
app = Flask(__name__)

@app.route("/")
def hello():
    msg = request.args.get('msg')
    if msg:
        return "<h1 style='color:blue'>desCartes! Message: {}</h1>".format(msg)
    else:
        return "<h1 style='color:blue'>desCartes!</h1>"

if __name__ == "__main__":
    app.run(host='0.0.0.0')