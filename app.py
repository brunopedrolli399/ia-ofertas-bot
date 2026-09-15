import os
import base64
import hashlib
import secrets
import requests
from flask import Flask, request, redirect

app = Flask(__name__)

CLIENT_ID = os.environ.get("ML_CLIENT_ID")
CLIENT_SECRET = os.environ.get("ML_CLIENT_SECRET")

REDIRECT_URI = "https://ia-ofertas-bot.onrender.com/oauth/mercadolivre/callback"

# Guarda temporariamente o code_verifier
pkce_verifier = None


@app.route("/")
def home():
    return "IA OFERTAS - servidor online!"


@app.route("/conectar/mercadolivre")
def conectar_mercadolivre():

    global pkce_verifier

    # Gera o code_verifier
    pkce_verifier = secrets.token_urlsafe(64)

    # Gera o code_challenge
    challenge = hashlib.sha256(
        pkce_verifier.encode("utf-8")
    ).digest()

    code_challenge = base64.urlsafe_b64encode(
        challenge
    ).decode("utf-8").rstrip("=")

    authorization_url = (
        "https://auth.mercadolivre.com.br/authorization"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )

    return redirect(authorization_url)


@app.route("/oauth/mercadolivre/callback")
def oauth_callback():

    global pkce_verifier

    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        return f"Erro na autorização: {error}", 400

    if not code:
        return "Código de autorização não recebido.", 400

    if not pkce_verifier:
        return "Code verifier não encontrado.", 400

    # Troca o código pelo Access Token
    response = requests.post(
        "https://api.mercadolibre.com/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": pkce_verifier
        },
        timeout=15
    )

    if response.status_code != 200:
        return (
            "<h1>IA OFERTAS</h1>"
            "<p>Erro ao obter Access Token.</p>"
            f"<pre>{response.text}</pre>"
        ), 400

    token_data = response.json()

    # Não mostramos os tokens na tela
    user_id = token_data.get("user_id")

    # Limpa o verifier depois da utilização
    pkce_verifier = None

    return (
        "<h1>IA OFERTAS</h1>"
        "<p>Mercado Livre conectado com sucesso!</p>"
        f"<p>Usuário conectado: {user_id}</p>"
    )


@app.route("/webhook/mercadolivre", methods=["POST"])
def mercadolivre_webhook():

    data = request.get_json(silent=True)

    print("Notificação recebida:", data)

    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
