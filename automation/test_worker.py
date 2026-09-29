import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from urllib.error import HTTPError

from worker import PROFILE, Instagram, database, deliver, prepare


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(PROFILE.read_text())
        self.now = datetime.now(timezone.utc)
        self.offer = {
            "id": "MLB123", "title": "Produto fictício para teste",
            "price": "99.90", "original_price": "129.90",
            "affiliate_label": "pedrollibruno",
            "affiliate_url": "https://meli.la/exemplo-nao-publicar",
            "image_url": "https://example.com/imagem-teste.jpg",
            "checked_at": self.now.isoformat(), "eligible": True, "available": True}

    def test_caption_and_exact_affiliate_link(self):
        post = prepare(self.offer, self.profile, self.now)
        self.assertIn("R$ 99,90", post["instagram_caption"])
        self.assertIn("23% OFF", post["instagram_caption"])
        self.assertIn("#publi", post["instagram_caption"])
        self.assertIn(self.offer["affiliate_url"], post["whatsapp_text"])
        self.assertIn("BLOQUEADO", post["whatsapp_status"])

    def test_rejects_stale_and_ineligible_offers(self):
        for delta in [{"eligible": False}, {"available": False},
                      {"affiliate_label": "outra-conta"},
                      {"checked_at": (self.now - timedelta(minutes=16)).isoformat()},
                      {"checked_at": (self.now + timedelta(seconds=1)).isoformat()},
                      {"price": "NaN"}, {"price": "-1"},
                      {"affiliate_url": "https://meli.la.evil.example/x"}]:
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                prepare({**self.offer, **delta}, self.profile, self.now)

    def test_does_not_invent_discount(self):
        self.offer.pop("original_price")
        self.assertNotIn("OFF", prepare(self.offer, self.profile, self.now)["instagram_caption"])

    def test_duplicate_does_not_publish_twice(self):
        with database(":memory:") as conn:
            client = Mock()
            client.create.return_value = "123"
            client.publish.return_value = "456"
            post = prepare(self.offer, self.profile, self.now)
            self.assertEqual(deliver(conn, post, client, self.profile, "2026-09-29"), "publicado")
            self.assertEqual(deliver(conn, post, client, self.profile, "2026-09-30"), "já registrado")
            client.publish.assert_called_once()

    def test_lost_response_requires_review_not_retry(self):
        with database(":memory:") as conn:
            client = Mock()
            client.create.return_value = "123"
            client.publish.side_effect = RuntimeError("Resposta perdida")
            post = prepare(self.offer, self.profile, self.now)
            with self.assertRaises(RuntimeError):
                deliver(conn, post, client, self.profile, "2026-09-29")
            self.assertEqual(conn.execute("SELECT status FROM attempts").fetchone()[0], "needs_review")
            self.assertEqual(deliver(conn, post, client, self.profile, "2026-09-29"), "já registrado")
            client.publish.assert_called_once()

    def test_daily_limit_blocks_calls(self):
        with database(":memory:") as conn:
            conn.executemany("INSERT INTO attempts VALUES (?, ?, 'published', NULL, NULL)",
                             [(str(i), "2026-09-29") for i in range(3)])
            conn.commit()
            client = Mock()
            self.assertEqual(deliver(conn, prepare(self.offer, self.profile, self.now), client,
                                     self.profile, "2026-09-29"), "limite diário")
            client.create.assert_not_called()

    def test_wrong_instagram_account_blocks(self):
        client = Instagram({"IG_USER_ID": "123", "META_GRAPH_VERSION": "v25.0", "IG_PAGE_ACCESS_TOKEN": "test"})
        client.call = Mock(return_value={"username": "outra-conta"})
        with self.assertRaises(ValueError):
            client.verify_account("iaofertastudo")

    def test_api_errors_do_not_expose_token(self):
        client = Instagram({"IG_USER_ID": "123", "META_GRAPH_VERSION": "v25.0", "IG_PAGE_ACCESS_TOKEN": "segredo"})
        client.opener = Mock()
        client.opener.open.side_effect = HTTPError("https://example.com", 401, "segredo", {}, None)
        with self.assertRaisesRegex(RuntimeError, "Meta retornou HTTP 401"):
            client.call("POST", "123/media")


if __name__ == "__main__":
    unittest.main()
