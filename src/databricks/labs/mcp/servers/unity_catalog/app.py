# from fastapi import FastAPI

# from databricks.labs.mcp.servers.unity_catalog.tools import get_prepared_mcp_app
# from databricks.labs.mcp.utils import get_app_index_route


# mcp = get_prepared_mcp_app()

# app = FastAPI(
#     lifespan=lambda _: mcp.session_manager.run(),
# )

# streamable_app = mcp.streamable_http_app()

# app.mount("/api", streamable_app)
# app.mount("/", get_app_index_route())
from databricks.labs.mcp.servers.unity_catalog.tools import get_prepared_mcp_app
from databricks.labs.mcp.utils import get_app_index_route
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
import os
import logging


mcp = get_prepared_mcp_app()

app = FastAPI(
    lifespan=lambda _: mcp.session_manager.run(),
)

# Define a middleware to capture user information from forwarded headers.
# This middleware will run for every incoming request to the FastAPI app.
class UserContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Retrieve the forwarded access token and host from the request headers.
        # Databricks Apps inject these headers for user authorization.
        user_access_token = request.headers.get('x-forwarded-access-token')
        
        # The Databricks host can also be found in x-forwarded-host or DATABRICKS_HOST env var.
        # Prioritize x-forwarded-host as it's directly from the request context.
        databricks_host = request.headers.get('x-forwarded-host') or os.getenv('DATABRICKS_HOST')

        # Initialize user_info in the request's state. This makes it accessible
        # to downstream route handlers and MCP tools.
        request.state.user_info = None 

        if user_access_token and databricks_host:
            try:
                # Create a Databricks SDK Config using the forwarded token and host.
                # This allows the SDK to authenticate as the user making the request.
                config = Config(
                    host=databricks_host,
                    token=user_access_token
                )
                # Initialize the WorkspaceClient with the user's credentials.
                workspace_client = WorkspaceClient(config=config)
                
                # Fetch the current user's details using the SDK.
                current_user = workspace_client.current_user.me()

                # Store essential user information in the request state.
                request.state.user_info = {
                    "user_id": current_user.id,
                    "user_name": current_user.user_name, # Typically the email address
                    "display_name": current_user.display_name,
                    "active": current_user.active,
                    # You can add more fields from current_user if needed,
                    # e.g., current_user.emails, current_user.groups, current_user.entitlements
                }
                logging.info(f"User identified: {request.state.user_info['display_name']} ({request.state.user_info['user_name']})")

            except Exception as e:
                # Log any errors encountered during user information retrieval.
                # This is crucial for debugging authentication issues.
                logging.error(f"Middleware Error: Could not retrieve user details with forwarded token: {e}")
                # The request will still proceed, but user_info will be None,
                # allowing downstream logic to handle cases where user context isn't available.
        else:
            logging.warning("Middleware: No 'x-forwarded-access-token' or 'x-forwarded-host' found in request headers.")

        # Pass the request to the next middleware or route handler.
        response = await call_next(request)
        return response

# Add the custom middleware to the FastAPI application.
# This must be done before mounting other applications if you want the middleware
# to apply to requests handled by those mounted apps (like the MCP server).
app.add_middleware(UserContextMiddleware)

# Mount the MCP streamable HTTP application at the /api path.
# This is where your MCP tools will be exposed.
app.mount("/api", mcp.streamable_http_app())

# Mount the default app index route at the root path.
app.mount("/", get_app_index_route())



 