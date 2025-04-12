import typer
import inspect
import importlib
import re
from typing import Any, Dict, List, Optional, Type, get_type_hints, Callable, Union
from enum import Enum
import httpx
import json
from pydantic import BaseModel
from fastapi import FastAPI, APIRouter, Query, Path, Body
from fastapi.routing import APIRoute


class FastAPIToTyper:
    def __init__(self, app: Union[FastAPI, str], base_url: Optional[str] = None):
        """
        Initialize the converter with either a FastAPI app instance or its import path.

        Args:
            app: Either a FastAPI instance or a string with the import path (e.g. 'myapp.main:app')
            base_url: Base URL for the API when making actual requests
        """
        self.typer_app = typer.Typer(help="CLI generated from FastAPI application")
        self.base_url = base_url

        if isinstance(app, str):
            # Import the app if a string is provided
            module_path, app_name = app.split(':')
            module = importlib.import_module(module_path)
            self.fastapi_app = getattr(module, app_name)
        else:
            self.fastapi_app = app

        self._build_cli()

    def _build_cli(self):
        """Build the CLI structure from FastAPI routes"""
        # Process all routes in the FastAPI app
        self._process_routes(self.fastapi_app.routes, self.typer_app, [])

    def _process_routes(self, routes, current_typer_app, path_prefix):
        """Process a list of routes and add them to the Typer app"""
        for route in routes:
            if isinstance(route, APIRouter):
                # Create a sub-app for each router
                sub_app = typer.Typer(help=f"Commands for {route.prefix}")
                current_typer_app.add_typer(sub_app, name=route.prefix.strip('/'))
                new_prefix = path_prefix + [route.prefix.strip('/')]
                self._process_routes(route.routes, sub_app, new_prefix)

            elif isinstance(route, APIRoute):
                # Process individual route
                self._add_route_to_typer(route, current_typer_app, path_prefix)

    def _add_route_to_typer(self, route: APIRoute, typer_app, path_prefix):
        """Convert a FastAPI route to a Typer command"""
        # Extract route information
        path = route.path
        http_method = route.methods.pop() if route.methods else "GET"
        endpoint_func = route.endpoint

        # Extract function signature to get parameters
        signature = inspect.signature(endpoint_func)
        type_hints = get_type_hints(endpoint_func)

        # Prepare path for command name
        # Remove path parameters and convert to command name
        command_name = self._path_to_command_name(path)

        # Create the actual Typer command
        def typer_command(**kwargs):
            """Execute the API command"""
            # Extract path parameters and query parameters
            path_params = {}
            query_params = {}
            body_data = {}

            for param_name, param_value in kwargs.items():
                if f"{{{param_name}}}" in path:
                    path_params[param_name] = param_value
                elif param_name == "body":
                    body_data = param_value
                else:
                    # Assume it's a query parameter
                    query_params[param_name] = param_value

            # Build the URL
            url = self._build_url(path, path_params)

            print(f"Executing {http_method} request to {url}")

            # Make the actual API call
            if http_method == "GET":
                response = httpx.get(url, params=query_params)
            elif http_method == "POST":
                response = httpx.post(url, params=query_params, json=body_data)
            elif http_method == "PUT":
                response = httpx.put(url, params=query_params, json=body_data)
            elif http_method == "DELETE":
                response = httpx.delete(url, params=query_params)
            else:
                raise ValueError(f"Unsupported HTTP method: {http_method}")

            # Print the response
            try:
                print(json.dumps(response.json(), indent=2))
            except:
                print(response.text)

            return response

        # Add parameter annotations to the Typer command
        for param_name, param in signature.parameters.items():
            if param_name in ("self", "request", "response"):
                continue

            param_type = type_hints.get(param_name, Any)

            # Check if this is a path parameter
            is_path_param = f"{{{param_name}}}" in path

            if is_path_param:
                # Path parameters become arguments
                typer_command = typer.Argument(
                    ...,  # Required
                    help=f"Path parameter {param_name}"
                )(typer_command, param_name)
            elif self._is_body_parameter(param):
                # Body parameters become JSON string options
                typer_command = typer.Option(
                    None,
                    "--body", "-b",
                    help="Request body as JSON string"
                )(typer_command, "body")
            else:
                # Query parameters become options
                default = param.default if param.default is not inspect.Parameter.empty else None
                required = param.default is inspect.Parameter.empty

                option_args = []
                if param_name:
                    option_args.append(f"--{param_name}")
                    option_args.append(f"-{param_name[0]}")

                typer_command = typer.Option(
                    default if not required else ...,
                    *option_args,
                    help=f"Query parameter {param_name}"
                )(typer_command, param_name)

        # Add help text based on the function's docstring
        typer_command.__doc__ = endpoint_func.__doc__ or f"{http_method} {path}"

        # Register the command with Typer
        typer_app.command(name=command_name)(typer_command)

    def _path_to_command_name(self, path: str) -> str:
        """Convert a path to a command name"""
        # Remove curly braces and convert to lowercase
        path = path.strip('/')
        # Replace path parameters with empty string
        path = re.sub(r'{[^}]+}', '', path)
        # Replace slashes and hyphens with underscores
        path = path.replace('/', '_').replace('-', '_')
        # Remove consecutive underscores
        path = re.sub(r'_+', '_', path)
        # Remove trailing underscores
        path = path.rstrip('_')

        return path

    def _build_url(self, path: str, path_params: Dict[str, Any]) -> str:
        """Build the URL with path parameters substituted"""
        url = path
        for param_name, param_value in path_params.items():
            url = url.replace(f"{{{param_name}}}", str(param_value))

        if self.base_url:
            return f"{self.base_url.rstrip('/')}/{url.lstrip('/')}"
        return url

    def _is_body_parameter(self, param) -> bool:
        """Check if a parameter is a request body"""
        # This is a simplified check - in real implementation we'd check for Body dependency
        # or if the parameter type is a Pydantic model
        return (
                param.annotation != inspect.Parameter.empty and
                (issubclass(param.annotation, BaseModel) if isinstance(param.annotation, type) else False)
        )

    def run(self):
        """Run the Typer application"""
        self.typer_app()


# Usage example
if __name__ == "__main__":
    # Example with importing an app
    # converter = FastAPIToTyper("myapp.main:app", base_url="http://localhost:8000")

    # Example with creating a test app
    app = FastAPI()


    @app.get("/items/{item_id}")
    def read_item(item_id: int, q: Optional[str] = None):
        """Get an item by its ID"""
        return {"item_id": item_id, "q": q}


    @app.post("/items/")
    def create_item(name: str, price: float):
        """Create a new item"""
        return {"name": name, "price": price}


    # Create a sub-router
    router = APIRouter(prefix="/users")


    @router.get("/{user_id}")
    def read_user(user_id: int):
        """Get a user by ID"""
        return {"user_id": user_id}


    app.include_router(router)

    # Convert to Typer
    converter = FastAPIToTyper(app, base_url="http://localhost:8000")
    converter.run()