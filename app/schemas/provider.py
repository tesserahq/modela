from pydantic import BaseModel


class ProviderModelSchema(BaseModel):
    id: str
    name: str


class ProviderSchema(BaseModel):
    id: str
    name: str
    models: list[ProviderModelSchema]
