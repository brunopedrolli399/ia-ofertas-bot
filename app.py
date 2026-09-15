import os
import requests
from flask import Flask, request

app = Flask(__name__)

CLIENT_ID = os.environ.get("ML_CLIENT_ID")
CLIENT_SECRET = os.environ.get("ML_CLIENT_SECRET")

REDIRECT_URI = "https://ia-ofertas-bot.onrender.com/oauth/mercadolivre/callback"


@app.route("/")
def home():
    return "IA OFERTAS - servidor online!"


@app.route("/oauth/mercadolivre/callback")
def oauth_callback():

    code = request.args.get("code")
    error = request.args.get("error")

    # Se o Mercado Livre retornar erro
    if error:
        return f"Erro na autorização: {error}", 400

    # Verifica se recebeu o código
    if not code:
        return "Código de autorização não recebido.", 400

    # Troca o código pelo Access Token
    response = requests.post(
        "https://api.mercadolibre.com/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI
        },
        timeout=15
    )

    # Se o Mercado Livre rejeitar a troca
    if response.status_code != 200:
        return (
            "<h1>IA OFERTAS</h1>"
            "<p>Erro ao obter Access Token.</p>"
            f"<pre>{response.text}</pre>"
        ), 400

    token_data = response.json()

    # Não mostramos os tokens na tela
    user_id = token_data.get("user_id")

    return (
        "<h1>IA OFERTAS</h1>"
        "<p>Autorização concluída com sucesso!</p>"
        f"<p>Usuário Mercado Livre conectado: {user_id}</p>"
    )


@app.route("/webhook/mercadolivre", methods=["POST"])
def mercadolivre_webhook():

    data = request.get_json(silent=True)

    print("Notificação recebida:", data)

    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
