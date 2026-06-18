"""Resource for Aveva API"""

import dagster as dg

# import requests
import httpx
from pydantic import PrivateAttr


class AvevaCredentials(dg.ConfigurableResource):
    """Aveva credentials"""

    client_id: str
    client_secret: str


class AvevaResource(dg.ConfigurableResource):
    """Reusable Aveva resource"""

    credentials: dg.ResourceDependency[AvevaCredentials]
    ocs_resource: str
    aveva_timeout: int = 30

    _client: httpx.Client = PrivateAttr()

    def setup_for_execution(self, context: dg.InitResourceContext) -> None:
        """Retrieves an access token from Aveva"""
        client = httpx.Client(timeout=self.aveva_timeout)
        wellknown_information = client.get(
            f"{self.ocs_resource}/identity/.well-known/openid-configuration",
        )
        token_url = wellknown_information.json()["token_endpoint"]

        #  use the client ID and Secret to get the needed bearer token
        token_information = client.post(
            token_url,
            data={
                "client_id": self.credentials.client_id,
                "client_secret": self.credentials.client_secret,
                "grant_type": "client_credentials",
            },
        )

        token = token_information.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})
        self._client = client

    def teardown_after_execution(self, context: dg.InitResourceContext) -> None:
        """Close and cleanup the session"""
        self._client.close()

    @property
    def client(self) -> httpx.Client:
        """Configured requests.Session with headers and timeout"""
        return self._client
