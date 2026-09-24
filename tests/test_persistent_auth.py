import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

import main
from config import settings
from jellyfin_client import jellyfin
from models import JellyfinConnection


class PersistentAuthTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        jellyfin.clear_connection()
        main.AUTH_VALIDATION_STATUS = "disconnected"

    def tearDown(self):
        jellyfin.clear_connection()
        main.AUTH_VALIDATION_STATUS = "disconnected"
        self.session.close()

    def test_remembered_login_persists_token_without_password(self):
        request = main.LoginRequest(
            url="http://jellyfin:8096/",
            username="daniel",
            password="secret",
            remember=True,
        )
        auth_result = {"access_token": "token-1", "user_id": "user-1"}

        with patch.object(
            jellyfin, "authenticate", AsyncMock(return_value=auth_result)
        ):
            result = asyncio.run(main.login(request, self.session))

        connection = self.session.get(JellyfinConnection, 1)
        self.assertEqual(result["remembered"], True)
        self.assertEqual(connection.server_url, "http://jellyfin:8096")
        self.assertEqual(connection.access_token, "token-1")
        self.assertFalse(hasattr(connection, "password"))
        self.assertEqual(settings.JELLYFIN_PASSWORD, "")

    def test_non_persistent_login_removes_previous_saved_connection(self):
        self.session.add(
            JellyfinConnection(
                id=1,
                server_url="http://old:8096",
                username="old",
                user_id="old-user",
                access_token="old-token",
            )
        )
        self.session.commit()
        request = main.LoginRequest(
            url="http://jellyfin:8096",
            username="daniel",
            password="secret",
            remember=False,
        )

        with patch.object(
            jellyfin,
            "authenticate",
            AsyncMock(return_value={"access_token": "token-2", "user_id": "user-2"}),
        ):
            result = asyncio.run(main.login(request, self.session))

        self.assertEqual(result["remembered"], False)
        self.assertIsNone(self.session.get(JellyfinConnection, 1))
        self.assertEqual(settings.JELLYFIN_TOKEN, "token-2")

    def test_invalid_url_does_not_replace_active_connection(self):
        jellyfin.configure_connection(
            "http://working:8096", "daniel", "user-1", "token-1"
        )
        request = main.LoginRequest(
            url="hhtps://broken",
            username="daniel",
            password="secret",
            remember=True,
        )

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(main.login(request, self.session))

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(settings.JELLYFIN_URL, "http://working:8096")
        self.assertEqual(settings.JELLYFIN_TOKEN, "token-1")

    def test_startup_restores_valid_saved_connection(self):
        self.session.add(
            JellyfinConnection(
                id=1,
                server_url="http://jellyfin:8096",
                username="daniel",
                user_id="user-1",
                access_token="token-1",
            )
        )
        self.session.commit()

        with patch.object(main, "engine", self.engine), patch.object(
            main, "create_db_and_tables"
        ), patch.object(
            jellyfin, "validate_connection", AsyncMock(return_value="valid")
        ):
            asyncio.run(main.on_startup())

        self.assertEqual(main.AUTH_VALIDATION_STATUS, "valid")
        self.assertEqual(settings.JELLYFIN_URL, "http://jellyfin:8096")
        self.assertEqual(settings.JELLYFIN_USER_ID, "user-1")
        self.assertEqual(settings.JELLYFIN_TOKEN, "token-1")

    def test_startup_removes_explicitly_rejected_token(self):
        self.session.add(
            JellyfinConnection(
                id=1,
                server_url="http://jellyfin:8096",
                username="daniel",
                user_id="user-1",
                access_token="revoked-token",
            )
        )
        self.session.commit()

        with patch.object(main, "engine", self.engine), patch.object(
            main, "create_db_and_tables"
        ), patch.object(
            jellyfin, "validate_connection", AsyncMock(return_value="invalid")
        ):
            asyncio.run(main.on_startup())

        self.session.expire_all()
        self.assertEqual(main.AUTH_VALIDATION_STATUS, "invalid")
        self.assertEqual(settings.JELLYFIN_TOKEN, "")
        self.assertIsNone(self.session.get(JellyfinConnection, 1))


if __name__ == "__main__":
    unittest.main()
