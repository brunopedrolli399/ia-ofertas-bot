"""Preparação e publicação de feed. Coletor de afiliados e WhatsApp pendentes.

Sem --publish, não acessa Instagram nem grava tentativas de publicação.
Executar em um único host Linux com armazenamento persistente para STATE_DB.
"""
import argparse
import fcntl
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

PROFILE = Path(__file__).with_name("profile.json")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def https_url(value, hosts=None):
    if not isinstance(value, str):
        raise ValueError("URL ausente")
    parsed = urlparse(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("URL HTTPS inválida")
    if hosts and parsed.hostname not in hosts:
        raise ValueError("Domínio de afiliado não reconhecido")
    return value


def price(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Preço inválido") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError("Preço inválido")
    return result.quantize(Decimal("0.01"))


def brl(value):
    return "R$ " + f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def prepare(offer, profile, now=None):
    now = now or datetime.now(timezone.utc)
    if not re.fullmatch(r"MLB-?[0-9]+", str(offer.get("id", ""))):
        raise ValueError("ID de produto inválido")
    if offer.get("affiliate_label") != profile["affiliate_label"]:
        raise ValueError("Etiqueta diferente da conta configurada")
    # Declarações do coletor confiável; não comprovam comissão sozinhas.
    if offer.get("eligible") is not True or offer.get("available") is not True:
        raise ValueError("Produto sem elegibilidade ou disponibilidade confirmada")
    checked = datetime.fromisoformat(offer.get("checked_at", ""))
    if checked.tzinfo is None or not timedelta(0) <= now - checked <= timedelta(
            minutes=profile["offer_max_age_minutes"]):
        raise ValueError("Oferta vencida, futura ou sem fuso horário")
    title = " ".join(str(offer.get("title", "")).split())
    if not title or len(title) > 250:
        raise ValueError("Título ausente ou muito longo")
    link = https_url(offer.get("affiliate_url"), {
        "meli.la", "mercadolivre.com", "www.mercadolivre.com",
        "mercadolivre.com.br", "www.mercadolivre.com.br"})
    image = https_url(offer.get("image_url"))
    current = price(offer.get("price"))
    line = brl(current)
    if offer.get("original_price") is not None:
        original = price(offer["original_price"])
        if original > current:
            discount = int((original - current) / original * 100)
            line = f"De {brl(original)} por {brl(current)} ({discount}% OFF)"
    disclosure = "#publi • Link de afiliado: posso receber comissão pela compra."
    note = "Preço e disponibilidade podem mudar."
    return {
        "id": offer["id"].replace("-", ""),
        "image_url": image,
        "instagram_caption": f"{title}\n{line}\n\nOfertas no grupo do WhatsApp: link na bio.\n{note}\n{disclosure}",
        "whatsapp_text": f"{title}\n{line}\n{link}\n{note}\n{disclosure}",
        "whatsapp_status": "BLOQUEADO: integração com grupo comum não implementada",
    }


class Instagram:
    """Instagram API with Facebook Login; token de Página, nunca senha."""
    def __init__(self, env=os.environ):
        self.user = env.get("IG_USER_ID", "")
        version = env.get("META_GRAPH_VERSION", "")
        token = env.get("IG_PAGE_ACCESS_TOKEN", "")
        if not self.user.isdigit() or not re.fullmatch(r"v[0-9]+\.0", version) or not token:
            raise ValueError("Configurar IG_USER_ID, META_GRAPH_VERSION e IG_PAGE_ACCESS_TOKEN")
        self.base = f"https://graph.facebook.com/{version}"
        self.opener = build_opener(NoRedirect)
        self.headers = {"Authorization": "Bearer " + token}

    def call(self, method, path, **kwargs):
        url = f"{self.base}/{path}"
        if kwargs.get("params"):
            url += "?" + urlencode(kwargs["params"])
        body = urlencode(kwargs["data"]).encode() if "data" in kwargs else None
        req = Request(url, data=body, headers=self.headers, method=method)
        try:
            with self.opener.open(req, timeout=30) as response:
                payload = response.read()
        except HTTPError as exc:
            raise RuntimeError(f"Meta retornou HTTP {exc.code}") from None
        except (URLError, OSError):
            raise RuntimeError("Falha de conexão com a Meta") from None
        try:
            data = json.loads(payload)
        except ValueError:
            raise RuntimeError("Resposta inválida da Meta") from None
        if not isinstance(data, dict) or "error" in data:
            raise RuntimeError("Resposta de erro da Meta")
        return data

    def verify_account(self, expected):
        data = self.call("GET", self.user, params={"fields": "username"})
        if data.get("username", "").lower() != expected.lower():
            raise ValueError("A conta autenticada não é @" + expected)

    def create(self, post):
        data = self.call("POST", f"{self.user}/media", data={
            "image_url": post["image_url"], "caption": post["instagram_caption"]})
        container = str(data.get("id", ""))
        if not container.isdigit():
            raise RuntimeError("A Meta não retornou um container válido")
        return container

    def wait_ready(self, container):
        for attempt in range(12):
            state = self.call("GET", container, params={"fields": "status_code"}).get("status_code")
            if state == "FINISHED":
                return
            if state != "IN_PROGRESS":
                raise RuntimeError("Container não está pronto para publicar")
            if attempt < 11:
                time.sleep(5)
        raise RuntimeError("Tempo de processamento excedido")

    def publish(self, container):
        data = self.call("POST", f"{self.user}/media_publish", data={"creation_id": container})
        media = str(data.get("id", ""))
        if not media.isdigit():
            raise RuntimeError("Publicação sem confirmação; conferir Instagram")
        return media


def database(path):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE IF NOT EXISTS attempts (
        product_id TEXT PRIMARY KEY, local_day TEXT NOT NULL,
        status TEXT NOT NULL, container_id TEXT, media_id TEXT)""")
    conn.commit()
    return conn


def deliver(conn, post, client, profile, local_day):
    # A reserva é persistida antes de qualquer envio. Falhas nunca são reenviadas
    # automaticamente: uma resposta perdida pode corresponder a um post publicado.
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM attempts WHERE product_id=?", (post["id"],)).fetchone():
            return "já registrado"
        count = conn.execute("SELECT count(*) FROM attempts WHERE local_day=?", (local_day,)).fetchone()[0]
        if count >= profile["daily_limit"]:
            return "limite diário"
        conn.execute("INSERT INTO attempts VALUES (?, ?, 'reserved', NULL, NULL)", (post["id"], local_day))
    try:
        container = client.create(post)
        with conn:
            conn.execute("UPDATE attempts SET container_id=?, status='processing' WHERE product_id=?", (container, post["id"]))
        client.wait_ready(container)
        with conn:
            conn.execute("UPDATE attempts SET status='publishing' WHERE product_id=?", (post["id"],))
        media = client.publish(container)
        with conn:
            conn.execute("UPDATE attempts SET status='published', media_id=? WHERE product_id=?", (media, post["id"]))
        return "publicado"
    except Exception:
        with conn:
            conn.execute("UPDATE attempts SET status='needs_review' WHERE product_id=?", (post["id"],))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offers", help="JSON produzido pelo futuro coletor autenticado")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    profile = json.loads(PROFILE.read_text())
    if args.status:
        print(json.dumps({"profile": profile,
            "affiliate_collector": "não implementado; acesso ainda não validado",
            "instagram": "cliente implementado; autenticação e teste real pendentes",
            "whatsapp": "grupo comum; integração não implementada",
            "scheduler": "não instalado",
            "publish_switch": os.environ.get("PUBLISH_ENABLED") == "true",
            "connection_verified": False}, ensure_ascii=False, indent=2))
        return
    if not args.offers:
        parser.error("Informe --offers ou --status")
    offers = json.loads(Path(args.offers).read_text())
    if not isinstance(offers, list) or len(offers) > 100:
        raise ValueError("Entrada deve ser uma lista com até 100 ofertas")
    # Validar tudo antes de qualquer publicação.
    posts = [prepare(offer, profile) for offer in offers]
    if not args.publish:
        print(json.dumps({"simulation": True, "posts": posts}, ensure_ascii=False, indent=2))
        return
    if os.environ.get("PUBLISH_ENABLED") != "true":
        raise ValueError("Publicação desativada: PUBLISH_ENABLED não é true")
    if os.environ.get("BIO_GROUP_LINK_CONFIRMED") != "true":
        raise ValueError("Confirmar que o convite do grupo está na bio antes de publicar a chamada")
    state = os.environ.get("STATE_DB")
    if not state or not Path(state).is_absolute():
        raise ValueError("STATE_DB deve apontar para um arquivo absoluto em disco persistente")
    client = Instagram()
    client.verify_account(profile["instagram_username"])
    with open(state + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        conn = database(state)
        try:
            for offer, post in zip(offers, posts):
                prepare(offer, profile)  # Revalidar validade imediatamente antes do envio.
                day = datetime.now(ZoneInfo(profile["timezone"])).date().isoformat()
                print(post["id"], deliver(conn, post, client, profile, day))
        finally:
            conn.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as exc:
        # Mensagens controladas: não imprimir exceções de rede com credenciais.
        if isinstance(exc, OSError):
            print("Falha ao acessar arquivo ou obter bloqueio de execução.")
        else:
            print(str(exc))
        raise SystemExit(1)
