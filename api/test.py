import pytest
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock
from fastapi import FastAPI, APIRouter, Body, Query, Path
from typing import Optional, List
from pydantic import BaseModel

from api.claude1 import FastAPIToTyper


# Import your FastAPIToTyper class


class Item(BaseModel):
    name: str
    price: float
    description: Optional[str] = None
    tags: List[str] = []


def create_test_fastapi_app():
    """Create a test FastAPI application with various endpoint types."""
    app = FastAPI()

    # GET endpoint with path and query parameters
    @app.get("/items/{item_id}")
    def read_item(
            item_id: int = Path(..., description="The ID of the item to retrieve"),
            q: Optional[str] = Query(None, description="Search query string"),
            skip: int = Query(0, description="Skip N items"),
            limit: int = Query(10, description="Limit results to N items")
    ):
        """Get an item by its ID"""
        return {
            "item_id": item_id,
            "q": q,
            "skip": skip,
            "limit": limit
        }

    # POST endpoint with body
    @app.post("/items/")
    def create_item(item: Item):
        """Create a new item"""
        return item

    # PUT endpoint with path param and body
    @app.put("/items/{item_id}")
    def update_item(item_id: int, item: Item):
        """Update an existing item"""
        return {"item_id": item_id, **item.dict()}

    # DELETE endpoint with path param
    @app.delete("/items/{item_id}")
    def delete_item(item_id: int):
        """Delete an item"""
        return {"deleted": item_id}

    # PATCH endpoint with path param and specific body fields
    @app.patch("/items/{item_id}/name")
    def patch_item_name(
            item_id: int,
            name: str = Body(..., embed=True)
    ):
        """Update an item's name"""
        return {"item_id": item_id, "name": name}

    @app.patch("/items/{item_id}/price")
    def patch_item_price(
            item_id: int,
            price: float = Body(..., embed=True)
    ):
        """Update an item's price"""
        return {"item_id": item_id, "price": price}

    # Create a sub-router for nested endpoints
    user_router = APIRouter(prefix="/users")

    @user_router.get("/{user_id}")
    def read_user(user_id: int):
        """Get a user by ID"""
        return {"user_id": user_id}

    @user_router.post("/")
    def create_user(username: str = Body(...), email: str = Body(...)):
        """Create a new user"""
        return {"username": username, "email": email}

    # Create a nested router (multiple levels)
    order_router = APIRouter(prefix="/orders")

    @order_router.get("/{order_id}")
    def get_order(order_id: int):
        """Get an order by ID"""
        return {"order_id": order_id}

    # Include the nested router in the user router
    user_router.include_router(order_router)

    # Include the user router in the main app
    app.include_router(user_router)

    return app


@pytest.fixture
def test_fastapi_app():
    return create_test_fastapi_app()


@pytest.fixture
def mock_http_response():
    mock_response = MagicMock()
    mock_response.json.return_value = {"result": "success"}
    mock_response.text = '{"result": "success"}'
    mock_response.raise_for_status = MagicMock()
    return mock_response


@pytest.fixture
def mock_httpx_client(mock_http_response):
    with patch("httpx.Client") as mock_client:
        client_instance = MagicMock()
        # Set up return values for different HTTP methods
        client_instance.get.return_value = mock_http_response
        client_instance.post.return_value = mock_http_response
        client_instance.put.return_value = mock_http_response
        client_instance.delete.return_value = mock_http_response
        client_instance.patch.return_value = mock_http_response
        client_instance.__enter__.return_value = client_instance

        mock_client.return_value = client_instance
        yield mock_client


def test_fastapitotyper_get_method(test_fastapi_app, mock_httpx_client):
    """Test GET method with path and query parameters."""
    converter = FastAPIToTyper(test_fastapi_app, base_url="http://localhost:8000")
    runner = CliRunner()

    # Debug to see available commands and parameters
    print("\nDEBUG - Available commands:")
    for cmd in converter.typer_app.registered_commands:
        print(f"Command: {cmd.name}")
        print(f"  Callback: {cmd.callback.__name__}")
        for param in cmd.params:
            print(f"  Param: {param.name}, Opts: {param.opts}")

    # Use the updated command name with HTTP method
    result = runner.invoke(converter.typer_app, ["items_get", "123", "--q", "search", "--skip", "5", "--limit", "20"])

    assert result.exit_code == 0, f"Failed with output: {result.output}"

    client = mock_httpx_client.return_value.__enter__.return_value
    client.get.assert_called_once()

    call_args, call_kwargs = client.get.call_args
    assert call_args[0] == "http://localhost:8000/items/123"
    assert call_kwargs["params"] == {"q": "search", "skip": "5", "limit": "20"}



def test_fastapitotyper_post_method(test_fastapi_app, mock_httpx_client):
    """Test POST method with body."""
    converter = FastAPIToTyper(test_fastapi_app, base_url="http://localhost:8000")
    runner = CliRunner()

    result = runner.invoke(converter.typer_app,
                           ["items", "--body", '{"name": "Test Item", "price": 29.99, "tags": ["test"]}'])

    assert result.exit_code == 0, f"Failed with output: {result.output}"

    client = mock_httpx_client.return_value.__enter__.return_value
    client.post.assert_called_once()

    call_args, call_kwargs = client.post.call_args
    assert call_args[0] == "http://localhost:8000/items/"
    assert call_kwargs["json"] == {"name": "Test Item", "price": 29.99, "tags": ["test"]}


def test_fastapitotyper_delete_method(test_fastapi_app, mock_httpx_client):
    """Test DELETE method with path parameter."""
    converter = FastAPIToTyper(test_fastapi_app, base_url="http://localhost:8000")
    runner = CliRunner()

    result = runner.invoke(converter.typer_app, ["items", "789"])

    assert result.exit_code == 0, f"Failed with output: {result.output}"

    client = mock_httpx_client.return_value.__enter__.return_value
    client.delete.assert_called_once()

    call_args, call_kwargs = client.delete.call_args
    assert call_args[0] == "http://localhost:8000/items/789"


def test_fastapitotyper_nested_routes(test_fastapi_app, mock_httpx_client):
    """Test nested routes."""
    converter = FastAPIToTyper(test_fastapi_app, base_url="http://localhost:8000")
    runner = CliRunner()

    # Test users endpoint
    result = runner.invoke(converter.typer_app, ["users", "202"])

    assert result.exit_code == 0, f"Failed with output: {result.output}"

    client = mock_httpx_client.return_value.__enter__.return_value
    client.get.assert_called()

    call_args, call_kwargs = client.get.call_args
    assert call_args[0] == "http://localhost:8000/users/202"