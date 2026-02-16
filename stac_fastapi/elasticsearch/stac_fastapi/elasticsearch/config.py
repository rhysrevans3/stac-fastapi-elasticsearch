"""API configuration."""

import logging
import os
import ssl
from typing import Any, Dict, Set, Union

from elasticsearch._async.client import AsyncElasticsearch

from elasticsearch import Elasticsearch  # type: ignore[attr-defined]
from stac_fastapi.core.base_settings import ApiBaseSettings
from stac_fastapi.core.utilities import get_bool_env
from stac_fastapi.sfeos_helpers.database import validate_refresh
from stac_fastapi.types.config import ApiSettings


def _es_config() -> Dict[str, Any]:
    # Determine the scheme (http or https)
    config = {
        "hosts": ["https://elasticsearch.ceda.ac.uk"],
        "headers": {
            "accept": "application/vnd.elasticsearch+json; compatible-with=8",
            "x-api-key": os.getenv("ES_API_KEY"),
        },
        "verify_certs": True,
        "ssl_show_warn": False,
        "ssl_version": ssl.TLSVersion.TLSv1_2,
    }

    return config


_forbidden_fields: Set[str] = {"type"}


class ElasticsearchSettings(ApiSettings, ApiBaseSettings):
    """
    API settings.

    Set enable_direct_response via the ENABLE_DIRECT_RESPONSE environment variable.
    If enabled, all API routes use direct response for maximum performance, but ALL FastAPI dependencies (including authentication, custom status codes, and validation) are disabled.
    Default is False for safety.
    """

    forbidden_fields: Set[str] = _forbidden_fields
    indexed_fields: Set[str] = {"datetime"}
    enable_response_models: bool = False
    enable_direct_response: bool = get_bool_env("ENABLE_DIRECT_RESPONSE", default=False)
    raise_on_bulk_error: bool = get_bool_env("RAISE_ON_BULK_ERROR", default=False)

    @property
    def database_refresh(self) -> Union[bool, str]:
        """
        Get the value of the DATABASE_REFRESH environment variable.

        Returns:
            Union[bool, str]: The value of DATABASE_REFRESH, which can be True, False, or "wait_for".
        """
        value = os.getenv("DATABASE_REFRESH", "false")
        return validate_refresh(value)

    @property
    def create_client(self):
        """Create es client."""
        return Elasticsearch(**_es_config())


class AsyncElasticsearchSettings(ApiSettings, ApiBaseSettings):
    """
    API settings.

    Set enable_direct_response via the ENABLE_DIRECT_RESPONSE environment variable.
    If enabled, all API routes use direct response for maximum performance, but ALL FastAPI dependencies (including authentication, custom status codes, and validation) are disabled.
    Default is False for safety.
    """

    forbidden_fields: Set[str] = _forbidden_fields
    indexed_fields: Set[str] = {"datetime"}
    enable_response_models: bool = False
    enable_direct_response: bool = get_bool_env("ENABLE_DIRECT_RESPONSE", default=False)
    raise_on_bulk_error: bool = get_bool_env("RAISE_ON_BULK_ERROR", default=False)

    @property
    def database_refresh(self) -> Union[bool, str]:
        """
        Get the value of the DATABASE_REFRESH environment variable.

        Returns:
            Union[bool, str]: The value of DATABASE_REFRESH, which can be True, False, or "wait_for".
        """
        value = os.getenv("DATABASE_REFRESH", "false")
        return validate_refresh(value)

    @property
    def create_client(self):
        """Create async elasticsearch client."""
        return AsyncElasticsearch(**_es_config())


# Warn at import if direct response is enabled (applies to either settings class)
if (
    ElasticsearchSettings().enable_direct_response
    or AsyncElasticsearchSettings().enable_direct_response
):
    logging.basicConfig(level=logging.WARNING)
    logging.warning(
        "ENABLE_DIRECT_RESPONSE is True: All FastAPI dependencies (including authentication) are DISABLED for all routes!"
    )
