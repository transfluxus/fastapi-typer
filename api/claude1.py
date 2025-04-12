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


def _extract_app_info(self) -> Dict[str, Any]:
    """Extract basic information about the FastAPI app."""
    if not self.openapi_schema:
        return {}

    info = self.openapi_schema.get('info', {})
    return {
        'title': info.get('title', 'FastAPI App'),
        'description': info.get('description', ''),
        'version': info.get('version', '0.1.0'),
        'terms_of_service': info.get('termsOfService', ''),
        'contact': info.get('contact', {}),
        'license': info.get('license', {})
    }


def _extract_route_metadata(self) -> Dict[str, Dict[str, Any]]:
    """Extract metadata for all routes from the OpenAPI schema."""
    if not self.openapi_schema:
        return {}

    paths = self.openapi_schema.get('paths', {})
    route_metadata = {}

    # Extract metadata for each path and method
    for path, methods in paths.items():
        for method, details in methods.items():
            if method.lower() == 'parameters':
                continue  # Skip common parameters

            route_key = f"{method.upper()}:{path}"

            # Extract parameter metadata
            params_metadata = {}
            parameters = details.get('parameters', [])
            for param in parameters:
                param_name = param.get('name')
                if param_name:
                    params_metadata[param_name] = {
                        'description': param.get('description', ''),
                        'required': param.get('required', False),
                        'schema': param.get('schema', {}),
                        'examples': param.get('examples', {}),
                        'example': param.get('example', None),
                        'location': param.get('in', 'query')  # query, path, header, cookie
                    }

            # Extract request body metadata
            body_metadata = {}
            request_body = details.get('requestBody', {})
            if request_body:
                content = request_body.get('content', {})
                # Usually application/json, but could be others
                for content_type, content_schema in content.items():
                    body_metadata[content_type] = {
                        'schema': content_schema.get('schema', {}),
                        'examples': content_schema.get('examples', {}),
                        'example': content_schema.get('example', None)
                    }

            # Store all metadata for this route
            route_metadata[route_key] = {
                'summary': details.get('summary', ''),
                'description': details.get('description', ''),
                'operationId': details.get('operationId', ''),
                'parameters': params_metadata,
                'requestBody': body_metadata,
                'responses': details.get('responses', {}),
                'tags': details.get('tags', []),
                'deprecated': details.get('deprecated', False)
            }

    return route_metadataimport
    typer


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
from enum import Enum
import yaml  # for OpenAPI schema parsing


class FastAPIToTyper:
    """Converts a FastAPI application to a Typer CLI application."""

    def __init__(
            self,
            app: Union[FastAPI, str],
            base_url: Optional[str] = None,
            app_name: str = None,
            app_description: str = None,
            extract_metadata: bool = True
    ):
        """
        Initialize the converter.

        Args:
            app: Either a FastAPI instance or a string with the import path (e.g. 'myapp.main:app')
            base_url: Base URL for the API when making actual requests
            app_name: Name of the generated CLI application (defaults to FastAPI app title)
            app_description: Description of the generated CLI application (defaults to FastAPI app description)
            extract_metadata: Whether to extract metadata from OpenAPI schema
        """
        # Import the app if a string is provided
        if isinstance(app, str):
            module_path, app_name_str = app.split(':')
            module = importlib.import_module(module_path)
            self.fastapi_app = getattr(module, app_name_str)
        else:
            self.fastapi_app = app

        # Extract metadata from the FastAPI app
        self.openapi_schema = self.fastapi_app.openapi() if extract_metadata else None
        self.app_info = self._extract_app_info()

        # Set app name and description based on FastAPI app if not provided
        self.app_name = app_name or self.app_info.get('title', 'FastAPI CLI')
        self.app_description = app_description or self.app_info.get('description',
                                                                    'CLI generated from FastAPI application')

        # Create the Typer app
        self.typer_app = typer.Typer(help=self.app_description)
        self.base_url = base_url
        self.verbose = False

        # Extract route metadata
        self.route_metadata = self._extract_route_metadata() if extract_metadata else {}

        # Add global options
        self._add_global_options()

        # Build the CLI structure
        self._build_cli()

    def _add_global_options(self):
        """Add global options to the CLI application."""
        # Add more detailed help if we have app info
        app_help = self.app_description
        if self.app_info:
            version = self.app_info.get('version', '')
            contact = self.app_info.get('contact', {})
            license_info = self.app_info.get('license', {})

            if version:
                app_help += f"\n\nVersion: {version}"

            if contact:
                contact_str = []
                if 'name' in contact:
                    contact_str.append(contact['name'])
                if 'email' in contact:
                    contact_str.append(f"<{contact['email']}>")
                if 'url' in contact:
                    contact_str.append(f"({contact['url']})")

                if contact_str:
                    app_help += f"\n\nContact: {' '.join(contact_str)}"

            if license_info:
                if 'name' in license_info:
                    app_help += f"\n\nLicense: {license_info['name']}"
                    if 'url' in license_info:
                        app_help += f" ({license_info['url']})"

        @self.typer_app.callback(help=app_help)
        def global_options(
                url: str = typer.Option(None, "--url", "-u", help="Override base URL for API requests"),
                verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output"),
                format: str = typer.Option("json", "--format", "-f",
                                           help="Output format (json, yaml, table)",
                                           choices=["json", "yaml", "table"]),
                timeout: float = typer.Option(30.0, "--timeout", "-t",
                                              help="Request timeout in seconds"),
                version: bool = typer.Option(False, "--version", help="Show version and exit")
        ):
            """Global options for the CLI."""
            if version:
                version_text = f"{self.app_name} "
                if self.app_info and self.app_info.get('version'):
                    version_text += f"v{self.app_info['version']}"
                typer.echo(version_text)
                raise typer.Exit()

            if url:
                self.base_url = url

            self.verbose = verbose
            self.output_format = format
            self.timeout = timeout

    def _build_cli(self):
        """Build the CLI structure from FastAPI routes."""
        self._process_routes(self.fastapi_app.routes, self.typer_app, [])

    def _process_routes(self, routes, current_typer_app, path_prefix):
        """Process routes recursively and add them to the appropriate Typer app."""
        # Group routes by tags for better organization
        tagged_routes = {}
        untagged_routes = []

        for route in routes:
            if isinstance(route, APIRouter):
                # Create a sub-app for each router
                router_name = route.prefix.strip('/').replace('-', '_') if route.prefix else "root"

                # Extract router metadata if available
                router_description = f"Commands for {route.prefix}" if route.prefix else "Root commands"
                if hasattr(route, 'tags') and route.tags:
                    if isinstance(route.tags[0], dict) and 'description' in route.tags[0]:
                        router_description = route.tags[0]['description']
                    elif isinstance(route.tags[0], str):
                        router_description = f"Commands for {route.tags[0]}"

                sub_app = typer.Typer(help=router_description)
                current_typer_app.add_typer(
                    sub_app,
                    name=router_name
                )
                new_prefix = path_prefix + [router_name]
                self._process_routes(route.routes, sub_app, new_prefix)

            elif isinstance(route, APIRoute):
                # Check if route has tags in OpenAPI schema
                http_method = list(route.methods)[0] if route.methods else "GET"
                route_key = f"{http_method}:{route.path}"
                route_meta = self.route_metadata.get(route_key, {})
                tags = route_meta.get('tags', [])

                if tags:
                    # Add to tagged routes
                    for tag in tags:
                        if tag not in tagged_routes:
                            tagged_routes[tag] = []
                        tagged_routes[tag].append(route)
                else:
                    # Add to untagged routes
                    untagged_routes.append(route)

        # Process tagged routes first - create a sub-app for each tag
        for tag, tag_routes in tagged_routes.items():
            # Find tag description if available in OpenAPI schema
            tag_description = f"Commands for {tag}"
            if self.openapi_schema and 'tags' in self.openapi_schema:
                for tag_info in self.openapi_schema['tags']:
                    if tag_info.get('name') == tag:
                        tag_description = tag_info.get('description', tag_description)
                        break

            tag_app = typer.Typer(help=tag_description)
            current_typer_app.add_typer(tag_app, name=tag.lower().replace(' ', '_'))

            # Add routes to tag app
            for route in tag_routes:
                self._add_route_to_typer(route, tag_app, path_prefix + [tag])

        # Process untagged routes
        for route in untagged_routes:
            self._add_route_to_typer(route, current_typer_app, path_prefix)

    def _add_route_to_typer(self, route: APIRoute, typer_app, path_prefix):
        """Convert a FastAPI route to a Typer command."""
        # Extract route information
        path = route.path
        http_method = list(route.methods)[0] if route.methods else "GET"
        endpoint_func = route.endpoint

        # Get route metadata from OpenAPI schema
        route_key = f"{http_method}:{path}"
        route_meta = self.route_metadata.get(route_key, {})

        # Get function signature and type hints
        try:
            signature = inspect.signature(endpoint_func)
            type_hints = get_type_hints(endpoint_func)
        except (ValueError, TypeError):
            # Skip if we can't inspect the function
            return

        # Generate a command name from the path
        command_name = self._path_to_command_name(path)

        # Get rich description from OpenAPI metadata
        summary = route_meta.get('summary', '')
        description = route_meta.get('description', '')

        # Use summary and/or description for the command help text
        help_text = None
        if summary and description:
            help_text = f"{summary}\n\n{description}"
        elif summary:
            help_text = summary
        elif description:
            help_text = description

        # Create a CLI command function with appropriate parameters
        cli_command = self._create_cli_command(endpoint_func, route, type_hints, route_meta)

        # Register the command with Typer
        typer_app.command(name=command_name, help=help_text)(cli_command)

    def _create_cli_command(self, endpoint_func, route, type_hints, route_meta=None):
        """Create a Typer command function from a FastAPI endpoint."""
        signature = inspect.signature(endpoint_func)
        parameters = []

        # Extract parameters metadata from route_meta
        param_metadata = {}
        if route_meta:
            param_metadata = route_meta.get('parameters', {})

        # Process each parameter from the original function
        for name, param in signature.parameters.items():
            if name in ("self", "request", "response"):
                continue

            # Get the type annotation
            annotation = type_hints.get(name, param.annotation)
            if annotation is inspect.Parameter.empty:
                annotation = str

            # Get parameter metadata
            param_meta = param_metadata.get(name, {})
            param_description = param_meta.get('description', f"Parameter {name}")
            param_example = param_meta.get('example', None)

            # Format help text with example if available
            help_text = param_description
            if param_example is not None:
                help_text = f"{param_description} (example: {param_example})"

            # Determine parameter type (path, query, or body)
            is_path_param = f"{{{name}}}" in route.path

            if is_path_param:
                # Path parameters become positional arguments
                new_param = inspect.Parameter(
                    name,
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=typer.Argument(..., help=help_text),
                    annotation=annotation
                )
            elif self._is_body_parameter(param):
                # Body parameters become JSON string options
                body_meta = route_meta.get('requestBody', {}) if route_meta else {}
                json_meta = body_meta.get('application/json', {}) if body_meta else {}
                body_example = json_meta.get('example', None)

                body_help = "Request body as JSON string"
                if body_example is not None:
                    body_help = f"{body_help} (example: {json.dumps(body_example)})"

                new_param = inspect.Parameter(
                    "body",
                    kind=inspect.Parameter.KEYWORD_ONLY,
                    default=typer.Option(None, "--body", "-b", help=body_help),
                    annotation=str
                )
            else:
                # Query parameters become options
                default_value = param.default if param.default is not inspect.Parameter.empty else None
                required = param.default is inspect.Parameter.empty

                # If the parameter has an enum schema, add choices
                choices = None
                schema = param_meta.get('schema', {})
                if schema and schema.get('enum') and isinstance(schema['enum'], list):
                    choices = schema['enum']

                # Create option with appropriate help text and possible choices
                new_param = inspect.Parameter(
                    name,
                    kind=inspect.Parameter.KEYWORD_ONLY,
                    default=typer.Option(
                        default_value if not required else ...,
                        f"--{name}",
                        f"-{name[0]}",
                        help=help_text,
                        # Include choices if available
                        **({'choices': choices} if choices else {})
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

        # For empty path, use "root"
        if not path:
            return "root"

        # Camel case the command for readability if it contains underscores
        if '_' in path:
            words = path.split('_')
            path = words[0] + ''.join(word.capitalize() for word in words[1:])

        return path

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