import json
import pytest
import inspect
from typing import Optional
import httpx
import typer
from fastapi import FastAPI, APIRouter
from typer.testing import CliRunner

from api.claude1 import FastAPIToTyper


# Adjust this import to match your module structure:
# from your_module import FastAPIToTyper


# --- Dummy Classes to Patch HTTP Requests ---

class DummyResponse:
    """A dummy response to simulate httpx.Response."""
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.text = json.dumps(data) if isinstance(data, dict) else str(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("Error", request=None, response=self)


class DummyClient:
    """A dummy httpx Client that returns preset responses."""
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def get(self, url, params=None, headers=None):
        # Simulate the GET /items/{item_id} endpoint.
        if "/items/" in url:
            item_id = int(url.rstrip("/").split("/")[-1])
            data = {"item_id": item_id, "q": params.get("q") if params else None}
            return DummyResponse(data)
        # Simulate the GET /users/{user_id} endpoint.
        if "/users/" in url:
            user_id = int(url.rstrip("/").split("/")[-1])
            data = {"user_id": user_id}
            return DummyResponse(data)
        return DummyResponse({})

    def post(self, url, params=None, json=None, headers=None):
        # Simulate the POST /items/ endpoint.
        if "/items/" in url:
            data = {"name": json.get("name"), "price": json.get("price")}
            return DummyResponse(data)
        return DummyResponse({})

    def put(self, url, params=None, json=None, headers=None):
        return DummyResponse(json)

    def delete(self, url, params=None, headers=None):
        return DummyResponse({"deleted": True})

    def patch(self, url, params=None, json=None, headers=None):
        return DummyResponse(json)


# Use Typer's CLI runner for testing
runner = CliRunner()


# --- Fixtures for the Test FastAPI App and Converter ---

@pytest.fixture
def test_app():
    """Define a test FastAPI application with endpoints and a sub-router."""
    app = FastAPI()

    @app.get("/items/{item_id}")
    def read_item(item_id: int, q: Optional[str] = None):
        """Get an item by its ID"""
        return {"item_id": item_id, "q": q}

    @app.post("/items/")
    def create_item(name: str, price: float):
        """Create a new item"""
        return {"name": name, "price": price}

    router = APIRouter(prefix="/users")

    @router.get("/{user_id}")
    def read_user(user_id: int):
        """Get a user by ID"""
        return {"user_id": user_id}

    app.include_router(router)
    return app


@pytest.fixture
def converter(test_app):
    """Instantiate the FastAPIToTyper converter with the test app."""
    conv = FastAPIToTyper(test_app, base_url="http://testserver")
    return conv


@pytest.fixture(autouse=True)
def patch_httpx(monkeypatch):
    """
    Patch httpx.Client with our dummy client so that no real HTTP requests are made.
    This fixture applies automatically to all tests.
    """
    monkeypatch.setattr(httpx, "Client", DummyClient)


# --- Tests for the CLI Commands ---

def test_get_item(converter):
    """
    Test the GET /items/{item_id} endpoint.
    The generated command name is derived from the path (becomes "items").
    """
    result = runner.invoke(
        converter.typer_app,
        ["items", "1", "--q", "testquery"]
    )

    # Check that the output contains the expected JSON response
    assert "Executing GET request to" in result.output
    assert '"item_id": 1' in result.output
    assert '"q": "testquery"' in result.output


def test_post_item(converter):
    """
    Test the POST /items/ endpoint.
    The command name for POST is also derived from the path (becomes "items").
    """
    result = runner.invoke(
        converter.typer_app,
        ["items", "--name", "testitem", "--price", "9.99"]
    )

    # Verify that the printed response contains the correct data
    assert "Executing POST request to" in result.output
    assert '"name": "testitem"' in result.output
    # JSON module converts numeric values, so check for the float as well.
    assert '"price": 9.99' in result.output


def test_get_user(converter):
    """
    Test the GET /users/{user_id} endpoint.
    The sub-router creates a nested command. For a route with only a path parameter,
    the command name defaults to "root" under the "users" sub-command.
    """
    # In our implementation, the sub-router is added with name "users"
    # and the route "/{user_id}" becomes command "root"
    result = runner.invoke(
        converter.typer_app,
        ["users", "root", "42"]
    )

    # Verify that the output contains the expected JSON response for a user
    assert "Executing GET request to" in result.output
    assert '"user_id": 42' in result.output


def test_global_options_override_base_url(converter):
    """
    Test that the global option to override the base URL (via --url)
    and the verbose flag (--verbose) work as expected.
    """
    result = runner.invoke(
        converter.typer_app,
        ["--url", "http://override", "--verbose", "items", "1", "--q", "overrideTest"]
    )
    # Check verbose output
    assert "Executing GET request to" in result.output
    # Check that the URL printed uses the overridden value.
    assert "http://override" in result.output


def test_invalid_json_body(converter):
    """
    Test that passing invalid JSON to a body parameter prints an error
    and exits with a non-zero status.
    """
    # For endpoints with a body parameter (such as POST),
    # pass an invalid JSON string to --body.
    result = runner.invoke(
        converter.typer_app,
        ["items", "--body", "not-a-json", "--name", "item", "--price", "9.99"]
    )
    # Expect an error message about the JSON validation.
    assert "Error: Body must be valid JSON" in result.output
    assert result.exit_code == 1
