import os
import base64
import hashlib
import secrets
import requests
import psycopg2
from flask import Flask, request, redirect

app = Flask(__name__)

CLIENT_ID = os.environ.get("ML_CLIENT_ID")
CLIENT_SECRET = os.environ.get("ML_CLIENT_SECRET")
DATABASE_URL = os.environ.get("DATABASE_URL")

REDIRECT_URI = "https://ia-ofertas-bot.onrender.com/oauth/mercadolivre/callback"

pkce_verifier = None


def get_db():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mercadolivre_tokens (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE NOT NULL,
            access_token TEXT NOT NULL,
            refresh_token TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


@app.route("/")
def home():
    return "IA OFERTAS - servidor online!"


@app.route("/conectar/mercadolivre")
def conectar_mercadolivre():

    global pkce_verifier

    pkce_verifier = secrets.token_urlsafe(64)

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

    user_id = token_data.get("user_id")
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 21600)

  if not user_id or not access_token or not refresh_token:
    campos = list(token_data.keys())

    return (
        "<h1>IA OFERTAS</h1>"
        "<p>Resposta recebida do Mercado Livre.</p>"
        f"<p>Campos recebidos: {campos}</p>"
    ), 400

    from datetime import datetime, timedelta

    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO mercadolivre_tokens
        (user_id, access_token, refresh_token, expires_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id)
        DO UPDATE SET
            access_token = EXCLUDED.access_token,
            refresh_token = EXCLUDED.refresh_token,
            expires_at = EXCLUDED.expires_at,
            updated_at = CURRENT_TIMESTAMP
    """, (
        user_id,
        access_token,
        refresh_token,
        expires_at
    ))

    conn.commit()
    cur.close()
    conn.close()

    pkce_verifier = None

    return (
        "<h1>IA OFERTAS</h1>"
        "<p>Mercado Livre conectado com sucesso!</p>"
        "<p>Tokens armazenados com segurança.</p>"
        f"<p>Usuário conectado: {user_id}</p>"
    )


@app.route("/webhook/mercadolivre", methods=["POST"])
def mercadolivre_webhook():

    data = request.get_json(silent=True)

    print("Notificação recebida:", data)

    return "OK", 200


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
