from __future__ import annotations

from .client import NetHuntClient


class NetHuntAutomationClient(NetHuntClient):
    @property
    def base_url(self) -> str:
        return self.settings.nethunt_automation_base_url

    @property
    def default_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "nethunt-mcp/0.1.0",
        }
        if self.settings.nethunt_automation_cookie:
            headers["Cookie"] = self.settings.nethunt_automation_cookie
        headers.update(self.settings.nethunt_automation_extra_headers)
        return headers
