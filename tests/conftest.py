"""
Pytest configuration and shared fixtures for RoyalBot-Portal tests.
"""
import os
import sys
import asyncio
import pytest
import uuid
from typing import AsyncGenerator, Generator
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# Add backend directories to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'user_backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'admin_backend'))

# Set test environment variables before importing any app modules
os.environ.setdefault('SECRET_KEY', 'test_secret_key_for_testing_only_min_32_chars')
os.environ.setdefault('DEBUG', 'True')
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('REDIS_URL', 'redis://localhost:7379/1')


# ==================== Database Fixtures ====================

@pytest.fixture(scope="session")
def test_engine():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return engine


@pytest.fixture(scope="function")
def test_db(test_engine) -> Generator[Session, None, None]:
    """
    Create a fresh database session for each test.

    Use this fixture for unit tests that need database access.
    """
    from database.models import Base
    from database import get_session

    # Create all tables
    Base.metadata.create_all(bind=test_engine)

    # Create session
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()

    # Override the dependency
    def override_get_session():
        try:
            yield session
        finally:
            pass

    # Store original to restore later
    original_get_session = get_session
    # Patch would happen in test setup

    yield session

    # Cleanup
    session.close()
    Base.metadata.drop_all(bind=test_engine)


# ==================== User Fixtures ====================

@pytest.fixture
def test_password() -> str:
    """A test password."""
    return "TestPassword123!"


@pytest.fixture
def test_user_data(test_password: str) -> dict:
    """Test user registration data."""
    return {
        "username": "testuser",
        "password": test_password,
        "email": "test@example.com",
    }


@pytest.fixture
def test_user(test_db: Session, test_user_data: dict) -> dict:
    """
    Create a test user in the database.

    Returns the user dict with id and hashed_password.
    """
    from database.models import WebUser
    from utils.security import get_password_hash

    user = WebUser(
        username=test_user_data["username"],
        password_hash=get_password_hash(test_user_data["password"]),
        email=test_user_data.get("email"),
        is_active=True,
    )
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "password": test_user_data["password"],  # Plain password for testing
        "is_active": user.is_active,
    }


@pytest.fixture
def test_admin_user(test_db: Session) -> dict:
    """Create an admin user for testing."""
    from database.models import WebUser
    from utils.security import get_password_hash

    admin_password = "AdminPassword123!"
    user = WebUser(
        username="admin",
        password_hash=get_password_hash(admin_password),
        email="admin@example.com",
        is_active=True,
        is_staff=True,
    )
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "password": admin_password,
        "is_active": user.is_active,
        "is_staff": user.is_staff,
    }


@pytest.fixture
def auth_headers(test_user: dict) -> dict:
    """
    Create authentication headers for a test user.

    Returns a dict with Authorization header.
    """
    from utils.security import create_access_token

    token = create_access_token(data={"sub": str(test_user["id"])})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(test_admin_user: dict) -> dict:
    """Create authentication headers for an admin user."""
    from utils.security import create_access_token

    token = create_access_token(data={"sub": str(test_admin_user["id"])})
    return {"Authorization": f"Bearer {token}"}


# ==================== FastAPI Test Client Fixtures ====================

@pytest.fixture(scope="function")
def user_client(test_db: Session) -> Generator[TestClient, None, None]:
    """
    Create a FastAPI TestClient for the user backend.

    This fixture automatically handles database setup/teardown.
    """
    from user_backend.main import app

    # Override the database dependency
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    from user_backend.database import get_session
    app.dependency_overrides[get_session] = override_get_db

    with TestClient(app) as client:
        yield client

    # Clean up overrides
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def admin_client(test_db: Session) -> Generator[TestClient, None, None]:
    """
    Create a FastAPI TestClient for the admin backend.
    """
    from admin_backend.main import app

    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    from admin_backend.database import get_session
    app.dependency_overrides[get_session] = override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
async def async_user_client(test_db: Session) -> AsyncGenerator[AsyncClient, None]:
    """
    Create an async HTTP client for testing user backend.

    Use this for testing async endpoints.
    """
    from user_backend.main import app

    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    from user_backend.database import get_session
    app.dependency_overrides[get_session] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()


# ==================== Emby Fixtures ====================

@pytest.fixture
def mock_emby_server(test_db: Session) -> dict:
    """Create a mock Emby server for testing."""
    from database.models import EmbyServer

    server = EmbyServer(
        name="Test Emby Server",
        url="http://emby.test:8096",
        api_key="test_api_key_12345",
        is_active=True,
        max_users=100,
        current_users=0,
    )
    test_db.add(server)
    test_db.commit()
    test_db.refresh(server)

    return {
        "id": server.id,
        "name": server.name,
        "url": server.url,
        "api_key": server.api_key,
    }


@pytest.fixture
def mock_subscription_plan(test_db: Session) -> dict:
    """Create a mock subscription plan for testing."""
    from database.models import SubscriptionPlan

    plan = SubscriptionPlan(
        name="Test Plan",
        description="A test subscription plan",
        price=9.99,
        duration_days=30,
        features='{"quality": "4K", "devices": 4}',
        is_active=True,
        is_popular=False,
        sort_order=1,
    )
    test_db.add(plan)
    test_db.commit()
    test_db.refresh(plan)

    return {
        "id": plan.id,
        "name": plan.name,
        "price": float(plan.price),
        "duration_days": plan.duration_days,
    }


# ==================== Mock Fixtures ====================

@pytest.fixture
def mock_telegram_user() -> dict:
    """Mock Telegram user data."""
    return {
        "id": 123456789,
        "username": "test_telegram_user",
        "first_name": "Test",
        "last_name": "User",
    }


@pytest.fixture
def mock_payment_callback() -> dict:
    """Mock payment callback data."""
    return {
        "pid": "test_order_123",
        "trade_no": "payment_gateway_trade_no",
        "name": "Test Product",
        "money": "9.99",
        "type": "alipay",
        "trade_status": "TRADE_SUCCESS",
    }


# ==================== Redis Fixture ====================

@pytest.fixture(scope="session")
def test_redis():
    """
    Create a test Redis client.

    Tests requiring Redis should use this fixture.
    Redis should be running on localhost:7379 for tests.
    """
    try:
        import redis
        client = redis.Redis(host='localhost', port=7379, db=1, decode_responses=True)
        # Test connection
        client.ping()
        yield client
        # Cleanup test database
        client.flushdb()
        client.close()
    except Exception as e:
        pytest.skip(f"Redis not available: {e}")
