class StructuredOutputValidationError(Exception):
    def __init__(
        self,
        message: str,
        *,
        validation_errors: list[dict],
        raw_content: str,
    ) -> None:
        super().__init__(message)
        self.validation_errors = validation_errors
        self.raw_content = raw_content
