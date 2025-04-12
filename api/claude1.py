import typer
import inspect
import functools
import importlib
import re
from typing import Any, Dict, List, Optional, Type, get_type_hints, Callable, Union, Set
import httpx
import json
from pydantic import BaseModel
from fastapi import FastAPI, APIRouter, Query, Path, Body
from fastapi.routing import APIRoute
from pathlib import Path as PathLib


class FastAPIToTyper:
    """Converts a FastAPI application to a Typer CLI application."""

    def __init__(
            self,
            app: Union[FastAPI, str],
            base_url: Optional[str] = None,
            app_name: str = "FastAPI CLI",
            app_description: str = "CLI generated from FastAPI application"
    ):
        """
        Initialize the converter.

        Args:
            app: Either a FastAPI instance or a string with the import path (e.g. 'myapp.main:app')
            base_url: Base URL for the API when making actual requests
            app_name: Name of the generated CLI application
            app_description: Description of the generated CLI application
        """
        self.typer_app = typer.Typer(help=app_description)
        self.base_url = base_url
        self.app_name = app_name
        self.verbose = False

        # Import the app if a string is provided
        if isinstance(app, str):
            module_path, app_name = app.split(':')
            module = importlib.import_module(module_path)
            self.fastapi_app = getattr(module, app_name)
        else:
            self.fastapi_app = app

        # Add global options
        self._add_global_options()

        # Build the CLI structure
        self._build_cli()

    def _add_global_options(self):
        """Add global options to the CLI application."""

        @self.typer_app.callback()
        def global_options(
                url: str = typer.Option(None, "--url", "-u", help="Override base URL for API requests"),
                verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output")
        ):
            """Global options for the CLI."""
            if url:
                self.base_url = url
            self.verbose = verbose

    def _build_cli(self):
        """Build the CLI structure from FastAPI routes."""
        self._process_routes(self.fastapi_app.routes, self.typer_app, [])

    def _process_routes(self, routes, current_typer_app, path_prefix):
        """Process routes recursively and add them to the appropriate Typer app."""
        for route in routes:
            if isinstance(route, APIRouter):
                # Create a sub-app for each router
                sub_app = typer.Typer(help=f"Commands for {route.prefix}")
                current_typer_app.add_typer(
                    sub_app,
                    name=route.prefix.strip('/').replace('-', '_')
                )
                new_prefix = path_prefix + [route.prefix.strip('/')]
                self._process_routes(route.routes, sub_app, new_prefix)

            elif isinstance(route, APIRoute):
                # Process individual route
                self._add_route_to_typer(route, current_typer_app, path_prefix)

    def _add_route_to_typer(self, route: APIRoute, typer_app, path_prefix):
        """Convert a FastAPI route to a Typer command."""
        # Extract route information
        path = route.path
        http_method = list(route.methods)[0] if route.methods else "GET"
        endpoint_func = route.endpoint

        # Get function signature and type hints
        try:
            signature = inspect.signature(endpoint_func)
            type_hints = get_type_hints(endpoint_func)
        except (ValueError, TypeError):
            # Skip if we can't inspect the function
            return

        # Generate a command name from the path
        command_name = self._path_to_command_name(path)

        # Create a CLI command function with appropriate parameters
        cli_command = self._create_cli_command(endpoint_func, route, type_hints)

        # Register the command with Typer
        typer_app.command(name=command_name)(cli_command)

    def _create_cli_command(self, endpoint_func, route, type_hints):
        """Create a Typer command function from a FastAPI endpoint."""
        signature = inspect.signature(endpoint_func)
        parameters = []

        # Process each parameter from the original function
        for name, param in signature.parameters.items():
            if name in ("self", "request", "response"):
                continue

            # Get the type annotation
            annotation = type_hints.get(name, param.annotation)
            if annotation is inspect.Parameter.empty:
                annotation = str

            # Determine parameter type (path, query, or body)
            is_path_param = f"{{{name}}}" in route.path

            if is_path_param:
                # Path parameters become positional arguments
                new_param = inspect.Parameter(
                    name,
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=typer.Argument(..., help=f"Path parameter {name}"),
                    annotation=annotation
                )
            elif self._is_body_parameter(param):
                # Body parameters become JSON string options
                new_param = inspect.Parameter(
                    "body",
                    kind=inspect.Parameter.KEYWORD_ONLY,
                    default=typer.Option(None, "--body", "-b", help="Request body as JSON string"),
                    annotation=str
                )
            else:
                # Query parameters become options
                default_value = param.default if param.default is not inspect.Parameter.empty else None
                required = param.default is inspect.Parameter.empty

                new_param = inspect.Parameter(
                    name,
                    kind=inspect.Parameter.KEYWORD_ONLY,
                    default=typer.Option(
                        default_value if not required else ...,
                        f"--{name}",
                        f"-{name[0]}",
                        help=f"Query parameter {name}"
                    ),
                    annotation=annotation
                )

            parameters.append(new_param)

        # Create a new signature with our modified parameters
        new_signature = inspect.Signature(parameters, return_annotation=None)

        # Get the HTTP method and path for this route
        http_method = list(route.methods)[0] if route.methods else "GET"
        path = route.path

        # Create the wrapper function for the CLI command
        @functools.wraps(endpoint_func)
        def cli_command(*args, **kwargs):
            """Execute the API command."""
            # Extract path parameters, query parameters, and body data
            path_params = {}
            query_params = {}
            body_data = None

            # Process positional arguments (path parameters)
            for i, (name, _) in enumerate([p for p in parameters if p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD]):
                if i < len(args):
                    path_params[name] = args[i]

            # Process keyword arguments
            for name, value in kwargs.items():
                if f"{{{name}}}" in path:
                    path_params[name] = value
                elif name == "body" and value is not None:
                    try:
                        body_data = json.loads(value)
                    except json.JSONDecodeError:
                        typer.echo(f"Error: Body must be valid JSON", err=True)
                        raise typer.Exit(code=1)
                else:
                    query_params[name] = value

            # Build the URL
            url = self._build_url(path, path_params)

            # Set request headers
            headers = {"Content-Type": "application/json"}

            # Show verbose output if enabled
            if self.verbose:
                typer.echo(f"Executing {http_method} request to {url}")
                if query_params:
                    typer.echo(f"Query parameters: {query_params}")
                if body_data:
                    typer.echo(f"Request body: {json.dumps(body_data, indent=2)}")

            try:
                # Create a client for making the request
                with httpx.Client() as client:
                    # Make the actual API call
                    if http_method == "GET":
                        response = client.get(url, params=query_params, headers=headers)
                    elif http_method == "POST":
                        response = client.post(url, params=query_params, json=body_data, headers=headers)
                    elif http_method == "PUT":
                        response = client.put(url, params=query_params, json=body_data, headers=headers)
                    elif http_method == "DELETE":
                        response = client.delete(url, params=query_params, headers=headers)
                    elif http_method == "PATCH":
                        response = client.patch(url, params=query_params, json=body_data, headers=headers)
                    else:
                        typer.echo(f"Unsupported HTTP method: {http_method}", err=True)
                        raise typer.Exit(code=1)

                # Check for HTTP errors
                response.raise_for_status()

                # Display response
                try:
                    typer.echo(json.dumps(response.json(), indent=2))
                except json.JSONDecodeError:
                    typer.echo(response.text)

                return response

            except httpx.HTTPStatusError as e:
                typer.echo(f"HTTP Error: {e}", err=True)
                try:
                    error_json = e.response.json()
                    typer.echo(f"Response: {json.dumps(error_json, indent=2)}", err=True)
                except:
                    typer.echo(f"Response: {e.response.text}", err=True)
                raise typer.Exit(code=e.response.status_code)
            except httpx.ConnectError:
                typer.echo(f"Error: Could not connect to {url}", err=True)
                raise typer.Exit(code=1)
            except httpx.TimeoutException:
                typer.echo(f"Error: Request to {url} timed out", err=True)
                raise typer.Exit(code=1)
            except httpx.RequestError as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(code=1)

        # Attach the new signature to the function
        cli_command.__signature__ = new_signature

        # Add help text from the original function's docstring
        cli_command.__doc__ = endpoint_func.__doc__ or f"{http_method} {path}"

        return cli_command

    def _build_url(self, path: str, path_params: Dict[str, Any]) -> str:
        """Build the URL with path parameters substituted."""
        url = path
        for param_name, param_value in path_params.items():
            url = url.replace(f"{{{param_name}}}", str(param_value))

        if self.base_url:
            return f"{self.base_url.rstrip('/')}/{url.lstrip('/')}"
        return url

    def _path_to_command_name(self, path: str) -> str:
        """Convert a path to a command name."""
        # Remove path parameters
        path = re.sub(r'{[^}]+}', '', path)

        # Replace special characters and make it CLI-friendly
        path = path.strip('/').replace('/', '_').replace('-', '_')

        # Remove consecutive underscores
        path = re.sub(r'_+', '_', path)

        # Remove trailing underscores
        path = path.rstrip('_')

        return path or "root"

    def _is_body_parameter(self, param) -> bool:
        """Check if a parameter is a request body."""
        # Check if it's a Pydantic model
        if param.annotation != inspect.Parameter.empty:
            if isinstance(param.annotation, type) and issubclass(param.annotation, BaseModel):
                return True

        # Alternative way: check if it has a Body dependency
        # (This is a simplified check - in a real implementation,
        # we would need to check the dependencies more thoroughly)
        param_default = param.default
        if hasattr(param_default, "__class__") and param_default.__class__.__name__ == "Body":
            return True

        return False

    def generate_schema(self):
        """Generate a schema for the Typer CLI."""
        # This could be used to generate shell completions or documentation
        commands = {}

        def collect_commands(app, prefix=""):
            for command in app.registered_commands:
                full_name = f"{prefix}{command.name}" if prefix else command.name
                commands[full_name] = {
                    "help": command.help,
                    "parameters": [
                        {
                            "name": p.name,
                            "type": str(p.type),
                            "required": p.required,
                            "help": p.help
                        }
                        for p in command.params
                    ]
                }

            for subapp in app.registered_groups:
                new_prefix = f"{prefix}{subapp.name} " if prefix else f"{subapp.name} "
                collect_commands(subapp.typer_instance, new_prefix)

        collect_commands(self.typer_app)
        return commands

    def run(self):
        """Run the Typer application."""
        self.typer_app()

    def save_to_package(self, output_dir: str):
        """
        Save the generated CLI as a standalone Python package.

        This is a placeholder - in a real implementation, this would
        generate a Python package with the CLI that can be installed
        independently of the original FastAPI application.
        """
        # Create the output directory
        output_path = PathLib(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Create package structure
        (output_path / "__init__.py").touch()

        # This would actually save the generated CLI code
        typer.echo(f"CLI package saved to {output_dir}")


# Example usage
if __name__ == "__main__":
    # Create a test FastAPI app
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