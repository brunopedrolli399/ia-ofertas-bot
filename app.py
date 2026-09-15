from flask import Flask, request

app = Flask(__name__)

@app.route("/")
def home():
    return "IA OFERTAS - servidor online!"

@app.route("/oauth/mercadolivre/callback")
def oauth_callback():
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        return f"Erro na autorização: {error}", 400

    if code:
        return "Autorização recebida com sucesso!", 200

    return "Aguardando autorização do Mercado Livre.", 200

@app.route("/webhook/mercadolivre", methods=["POST"])
def mercadolivre_webhook():
    data = request.get_json(silent=True)

    print("Notificação recebida:", data)

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
