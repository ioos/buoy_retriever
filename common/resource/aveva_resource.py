"""Reusable S3FS resource"""

import dagster as dg
import requests
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
    _token: str = PrivateAttr()

    def setup_for_execution(self, context: dg.InitResourceContext) -> None:
        print("SETUP EXECUTION")

        wellknown_information = requests.get(
            f"{self.ocs_resource}/identity/.well-known/openid-configuration",
            timeout=self.aveva_timeout,
        )
        token_url = wellknown_information.json()["token_endpoint"]

        # Step 3: use the client ID and Secret to get the needed bearer token
        token_information = requests.post(
            token_url,
            timeout=self.aveva_timeout,
            data={
                "client_id": self.credentials.client_id,
                "client_secret": self.credentials.client_secret,
                "grant_type": "client_credentials",
            },
        )

        self._token = token_information.json()["access_token"]
        print(f"Set Token to {self._token}")

    @property
    def aveva_token(self) -> str:
        """Access the aveva client"""
        return self._token
