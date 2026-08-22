from dataclasses import dataclass

from core.version import APP_RELEASE_CHANNEL


@dataclass(frozen=True)
class ReleaseConfig:
    channel: str = APP_RELEASE_CHANNEL

    @property
    def is_development(self) -> bool:
        return self.channel.lower() == "dev"

    @property
    def is_release_candidate(self) -> bool:
        return self.channel.lower() == "rc"

    @property
    def allow_administrator_tool(self) -> bool:
        return self.is_development

    @property
    def show_development_warning(self) -> bool:
        return self.is_development

    @property
    def update_channel(self) -> str:
        return self.channel.lower()
