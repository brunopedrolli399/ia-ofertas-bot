import os
import base64
import hashlib
import secrets
import requests
import psycopg2

from datetime import datetime, timedelta
from flask import Flask, request, redirect, jsonify


app = Flask(__name__)


CLIENT_ID = os.environ.get("ML_CLIENT_ID")
CLIENT_SECRET = os.environ.get("ML_CLIENT_SECRET")
DATABASE_URL = os.environ.get("DATABASE_URL")

REDIRECT_URI = "https://ia-ofertas-bot.onrender.com/oauth/mercadolivre/callback"

pkce_verifier = None


# ============================================================
# BANCO DE DADOS
# ============================================================

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


# ============================================================
# RENOVAÇÃO DO TOKEN
# ============================================================

def refresh_mercadolivre_token(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT refresh_token
        FROM mercadolivre_tokens
        WHERE user_id = %s
    """, (user_id,))

    result = cur.fetchone()

    if not result:
        cur.close()
        conn.close()
        return None

    refresh_token = result[0]

    response = requests.post(
        "https://api.mercadolibre.com/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token
        },
        timeout=15
    )

    if response.status_code != 200:

        print(
            "Erro ao renovar token:",
            response.status_code,
            response.text
        )

        cur.close()
        conn.close()

        return None

    token_data = response.json()

    new_access_token = token_data.get("access_token")
    new_refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 21600)

    if not new_access_token or not new_refresh_token:

        print("Resposta de renovação sem os tokens necessários.")

        cur.close()
        conn.close()

        return None

    expires_at = datetime.utcnow() + timedelta(
        seconds=expires_in
    )

    cur.execute("""
        UPDATE mercadolivre_tokens
        SET
            access_token = %s,
            refresh_token = %s,
            expires_at = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = %s
    """, (
        new_access_token,
        new_refresh_token,
        expires_at,
        user_id
    ))

    conn.commit()

    cur.close()
    conn.close()

    print(
        "Access Token renovado com sucesso para o usuário:",
        user_id
    )

    return new_access_token


# ============================================================
# OBTER TOKEN VÁLIDO
# ============================================================

def get_valid_access_token(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT access_token, expires_at
        FROM mercadolivre_tokens
        WHERE user_id = %s
    """, (user_id,))

    result = cur.fetchone()

    cur.close()
    conn.close()

    if not result:
        return None

    access_token, expires_at = result

    if datetime.utcnow() < expires_at:
        return access_token

    print("Access Token expirado. Renovando...")

    return refresh_mercadolivre_token(user_id)


# ============================================================
# PÁGINA INICIAL
# ============================================================

@app.route("/")
def home():

    return "IA OFERTAS - servidor online!"


# ============================================================
# CONEXÃO COM MERCADO LIVRE
# ============================================================

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


# ============================================================
# CALLBACK OAUTH
# ============================================================

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

    expires_at = datetime.utcnow() + timedelta(
        seconds=expires_in
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO mercadolivre_tokens
        (
            user_id,
            access_token,
            refresh_token,
            expires_at
        )
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


# ============================================================
# TESTE DO TOKEN
# ============================================================

@app.route("/testar/token/<user_id>")
def testar_token(user_id):

    access_token = get_valid_access_token(user_id)

    if not access_token:

        return (
            "<h1>IA OFERTAS</h1>"
            "<p>Não foi possível obter um Access Token válido.</p>"
        ), 400

    return (
        "<h1>IA OFERTAS</h1>"
        "<p>Access Token válido.</p>"
        "<p>O sistema conseguiu acessar o token armazenado.</p>"
    )


# ============================================================
# TESTE DOS ANÚNCIOS DO VENDEDOR
# ============================================================

@app.route("/testar/anuncios/<user_id>")
def testar_anuncios(user_id):

    # --------------------------------------------------------
    # 1. Obter token válido
    # --------------------------------------------------------

    access_token = get_valid_access_token(user_id)

    if not access_token:

        return jsonify({
            "sucesso": False,
            "erro": "Não foi possível obter um Access Token válido."
        }), 401

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    # --------------------------------------------------------
    # 2. Buscar IDs dos anúncios ativos
    # --------------------------------------------------------

    search_url = (
        f"https://api.mercadolibre.com/"
        f"users/{user_id}/items/search"
    )

    search_response = requests.get(
        search_url,
        headers=headers,
        params={
            "status": "active",
            "limit": 20
        },
        timeout=15
    )

    if search_response.status_code != 200:

        return jsonify({
            "sucesso": False,
            "etapa": "buscar_anuncios",
            "status_api": search_response.status_code,
            "erro": "O Mercado Livre recusou a consulta dos anúncios."
        }), search_response.status_code

    search_data = search_response.json()

    item_ids = search_data.get("results", [])

    total_anuncios = search_data.get(
        "paging",
        {}
    ).get(
        "total",
        len(item_ids)
    )

    # --------------------------------------------------------
    # 3. Se não houver anúncios
    # --------------------------------------------------------

    if not item_ids:

        return jsonify({
            "sucesso": True,
            "usuario": user_id,
            "total_anuncios": total_anuncios,
            "anuncios": []
        })


    # --------------------------------------------------------
    # 4. Buscar detalhes dos anúncios
    # --------------------------------------------------------

    ids = ",".join(item_ids)

    bulk_url = (
        "https://api.mercadolibre.com/items/bulk"
    )

    bulk_response = requests.get(
        bulk_url,
        headers=headers,
        params={
            "ids": ids,
            "attributes": (
                "body.id,"
                "body.title,"
                "body.price,"
                "body.available_quantity,"
                "body.sold_quantity,"
                "body.status,"
                "body.category_id,"
                "body.permalink"
            )
        },
        timeout=20
    )

    if bulk_response.status_code != 200:

        return jsonify({
            "sucesso": False,
            "etapa": "detalhes_anuncios",
            "status_api": bulk_response.status_code,
            "erro": "Não foi possível consultar os detalhes dos anúncios."
        }), bulk_response.status_code


    # --------------------------------------------------------
    # 5. Montar resposta segura
    # --------------------------------------------------------

    bulk_data = bulk_response.json()

    anuncios = []

    for item in bulk_data:

        body = item.get("body", {})

        anuncio = {
            "id": body.get("id"),
            "titulo": body.get("title"),
            "preco": body.get("price"),
            "estoque": body.get("available_quantity"),
            "vendidos": body.get("sold_quantity"),
            "status": body.get("status"),
            "categoria": body.get("category_id"),
            "link": body.get("permalink")
        }

        anuncios.append(anuncio)


    # --------------------------------------------------------
    # 6. Retornar somente dados seguros
    # --------------------------------------------------------

    return jsonify({
        "sucesso": True,
        "usuario": user_id,
        "total_anuncios": total_anuncios,
        "anuncios_retornados": len(anuncios),
        "anuncios": anuncios
    })


# ============================================================
# WEBHOOK MERCADO LIVRE
# ============================================================

@app.route(
    "/webhook/mercadolivre",
    methods=["POST"]
)
def mercadolivre_webhook():

    data = request.get_json(
        silent=True
    )

    print(
        "Notificação recebida:",
        data
    )

    return "OK", 200


# ============================================================
# INICIALIZAÇÃO DO BANCO
# ============================================================

init_db()


# ============================================================
# EXECUÇÃO LOCAL
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=10000
    )
