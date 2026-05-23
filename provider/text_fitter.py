from dify_plugin import ToolProvider
class TextFitterProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict) -> None:
        # This tool does not require any credentials (no API keys needed).
        # The validation always passes.
        pass
