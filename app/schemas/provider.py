from pydantic import BaseModel


class ParameterSpec(BaseModel):
    default: float | int | None = None
    min: float | None = None
    max: float | None = None


class ProviderParameters(BaseModel):
    temperature: ParameterSpec | None = None
    top_p: ParameterSpec | None = None
    max_tokens: ParameterSpec | None = None
    exclusive_parameter_groups: list[list[str]] | None = None


class ProviderModelSchema(BaseModel):
    id: str
    name: str


class ProviderSchema(BaseModel):
    id: str
    name: str
    models: list[ProviderModelSchema]
    parameters: ProviderParameters | None = None
