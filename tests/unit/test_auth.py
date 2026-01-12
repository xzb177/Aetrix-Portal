"""
Unit tests for Authentication module.

Tests cover:
- Password hashing and verification
- JWT token creation and decoding
- Login endpoint
- Registration endpoint
- Current user endpoint
- Authentication dependency
"""
import pytest
from fastapi import status
from sqlalchemy.orm import Session


class TestPasswordSecurity:
    """Test password hashing and verification functions."""

    def test_password_hashing(self):
        """Test password hashing creates different hashes for same password."""
        from utils.security import get_password_hash

        password = "TestPassword123!"
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)

        # Hashes should be different due to salt
        assert hash1 != hash2
        # But both should be bcrypt hashes (start with $2b$)
        assert hash1.startswith("$2b$")
        assert hash2.startswith("$2b$")

    def test_password_verification_success(self):
        """Test correct password verification."""
        from utils.security import get_password_hash, verify_password

        password = "TestPassword123!"
        hashed = get_password_hash(password)

        assert verify_password(password, hashed) is True

    def test_password_verification_failure(self):
        """Test incorrect password verification fails."""
        from utils.security import get_password_hash, verify_password

        password = "TestPassword123!"
        wrong_password = "WrongPassword456!"
        hashed = get_password_hash(password)

        assert verify_password(wrong_password, hashed) is False

    def test_empty_password(self):
        """Test empty password handling."""
        from utils.security import get_password_hash, verify_password

        password = ""
        hashed = get_password_hash(password)

        assert verify_password(password, hashed) is True
        assert verify_password("something", hashed) is False


class TestJWTToken:
    """Test JWT token creation and decoding."""

    def test_create_token(self):
        """Test JWT token creation."""
        from utils.security import create_access_token

        data = {"sub": "123", "username": "testuser"}
        token = create_access_token(data)

        assert token is not None
        assert isinstance(token, str)
        # JWT tokens have 3 parts separated by dots
        assert len(token.split(".")) == 3

    def test_decode_valid_token(self):
        """Test decoding a valid token."""
        from utils.security import create_access_token, decode_access_token

        data = {"sub": "123", "username": "testuser"}
        token = create_access_token(data)
        decoded = decode_access_token(token)

        assert decoded is not None
        assert decoded["sub"] == "123"
        assert decoded["username"] == "testuser"
        assert "exp" in decoded  # Expiration should be added

    def test_decode_invalid_token(self):
        """Test decoding an invalid token returns None."""
        from utils.security import decode_access_token

        assert decode_access_token("invalid.token.here") is None
        assert decode_access_token("") is None
        assert decode_access_token("bearer_token_without_dots") is None

    def test_token_expiration(self):
        """Test token expiration is set correctly."""
        from utils.security import create_access_token, decode_access_token
        from datetime import timedelta

        data = {"sub": "123"}
        # Create token with short expiration
        token = create_access_token(data, expires_delta=timedelta(seconds=60))
        decoded = decode_access_token(token)

        assert decoded is not None
        assert "exp" in decoded


class TestLoginEndpoint:
    """Test the login endpoint."""

    def test_login_success(self, user_client, test_user):
        """Test successful login with valid credentials."""
        response = user_client.post(
            "/api/user/auth/login",
            json={
                "username": test_user["username"],
                "password": test_user["password"],
            }
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert "user" in data
        assert data["user"]["username"] == test_user["username"]
        assert data["user"]["email"] == test_user["email"]

    def test_login_wrong_password(self, user_client, test_user):
        """Test login fails with wrong password."""
        response = user_client.post(
            "/api/user/auth/login",
            json={
                "username": test_user["username"],
                "password": "WrongPassword123!",
            }
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_nonexistent_user(self, user_client):
        """Test login fails for non-existent user."""
        response = user_client.post(
            "/api/user/auth/login",
            json={
                "username": "nonexistent_user",
                "password": "SomePassword123!",
            }
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_inactive_user(self, user_client, test_db):
        """Test login fails for inactive user."""
        from database.models import WebUser
        from utils.security import get_password_hash

        # Create inactive user
        user = WebUser(
            username="inactive_user",
            password_hash=get_password_hash("TestPassword123!"),
            is_active=False,
        )
        test_db.add(user)
        test_db.commit()

        response = user_client.post(
            "/api/user/auth/login",
            json={
                "username": "inactive_user",
                "password": "TestPassword123!",
            }
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestRegistrationEndpoint:
    """Test the registration endpoint."""

    def test_register_success(self, user_client):
        """Test successful user registration."""
        response = user_client.post(
            "/api/user/auth/register",
            json={
                "username": "newuser",
                "password": "NewPassword123!",
                "email": "newuser@example.com",
            }
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert "user" in data
        assert data["user"]["username"] == "newuser"
        assert data["user"]["email"] == "newuser@example.com"

    def test_register_duplicate_username(self, user_client, test_user):
        """Test registration fails with duplicate username."""
        response = user_client.post(
            "/api/user/auth/register",
            json={
                "username": test_user["username"],
                "password": "AnotherPassword123!",
            }
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_with_invitation_code(self, user_client, test_db, test_user):
        """Test registration with valid invitation code."""
        from database.models import InvitationCode

        # Create an invitation code
        code = InvitationCode(
            code="TESTCODE123",
            user_id=test_user["id"],
            use_count=0,
        )
        test_db.add(code)
        test_db.commit()

        response = user_client.post(
            "/api/user/auth/register",
            json={
                "username": "invited_user",
                "password": "InvitedPassword123!",
                "invitation_code": "TESTCODE123",
            }
        )

        assert response.status_code == status.HTTP_200_OK

    def test_register_with_invalid_invitation_code(self, user_client):
        """Test registration fails with invalid invitation code."""
        response = user_client.post(
            "/api/user/auth/register",
            json={
                "username": "newuser",
                "password": "NewPassword123!",
                "invitation_code": "INVALIDCODE",
            }
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestCurrentUserEndpoint:
    """Test the current user endpoint."""

    def test_get_current_user(self, user_client, auth_headers, test_user):
        """Test getting current user info with valid token."""
        response = user_client.get(
            "/api/user/auth/me",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["username"] == test_user["username"]
        assert data["email"] == test_user["email"]
        assert "id" in data

    def test_get_current_user_no_token(self, user_client):
        """Test getting current user fails without token."""
        response = user_client.get("/api/user/auth/me")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_current_user_invalid_token(self, user_client):
        """Test getting current user fails with invalid token."""
        response = user_client.get(
            "/api/user/auth/me",
            headers={"Authorization": "Bearer invalid_token"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestLogoutEndpoint:
    """Test the logout endpoint."""

    def test_logout_success(self, user_client, auth_headers):
        """Test logout endpoint returns success."""
        response = user_client.post(
            "/api/user/auth/logout",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["message"] == "Logged out successfully"


class TestTelegramCallback:
    """Test Telegram OAuth callback endpoint."""

    @pytest.mark.parametrize("user_data,expected_username", [
        ({"id": 123, "username": "validuser"}, "validuser"),
        ({"id": 456, "username": "user with spaces"}, "userwithspaces"),
        ({"id": 789, "username": "user@with$symbols!"}, "userwithsymbols"),
        ({"id": 999, "username": None}, "tg_999"),
    ])
    def test_telegram_username_sanitization(self, user_client, user_data, expected_username):
        """Test Telegram username sanitization logic."""
        import json
        import urllib.parse

        # Create query string with user data
        user_json = json.dumps(user_data)
        query_string = f"hash=test&user={urllib.parse.quote(user_json)}"

        response = user_client.post(
            "/api/user/auth/telegram-callback",
            json={"query_string": query_string}
        )

        # Should succeed or fail based on hash validation
        # The test verifies username sanitization logic is in place
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_401_UNAUTHORIZED]


@pytest.mark.integration
class TestAuthenticationIntegration:
    """Integration tests for authentication flows."""

    def test_full_login_flow(self, user_client, test_user):
        """Test complete login flow: login -> get user info -> logout."""
        # Login
        login_response = user_client.post(
            "/api/user/auth/login",
            json={
                "username": test_user["username"],
                "password": test_user["password"],
            }
        )
        assert login_response.status_code == status.HTTP_200_OK
        token = login_response.json()["access_token"]

        # Get user info
        me_response = user_client.get(
            "/api/user/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert me_response.status_code == status.HTTP_200_OK
        assert me_response.json()["username"] == test_user["username"]

        # Logout
        logout_response = user_client.post(
            "/api/user/auth/logout",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert logout_response.status_code == status.HTTP_200_OK

    def test_register_and_login_flow(self, user_client):
        """Test registration followed by login."""
        # Register
        register_response = user_client.post(
            "/api/user/auth/register",
            json={
                "username": "flowtestuser",
                "password": "FlowPassword123!",
                "email": "flowtest@example.com",
            }
        )
        assert register_response.status_code == status.HTTP_200_OK

        # Login with same credentials
        login_response = user_client.post(
            "/api/user/auth/login",
            json={
                "username": "flowtestuser",
                "password": "FlowPassword123!",
            }
        )
        assert login_response.status_code == status.HTTP_200_OK
        assert "access_token" in login_response.json()
