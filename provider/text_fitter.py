from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError


class TextFitterProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict) -> None:
        try:
            pass
        except Exception as e:
            raise ToolProviderCredentialValidationError(str(e))
