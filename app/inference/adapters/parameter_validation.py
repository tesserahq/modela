from app.exceptions.invalid_parameter_error import InvalidParameterError
from app.inference.adapters.registry import get_adapter
from app.schemas.provider import ParameterSpec


def _get_spec(provider: str, field: str) -> ParameterSpec | None:
    try:
        adapter = get_adapter(provider)
    except ValueError:
        return None
    if adapter.parameters is None:
        return None
    return getattr(adapter.parameters, field, None)


def _get_exclusive_groups(provider: str) -> list[list[str]]:
    try:
        adapter = get_adapter(provider)
    except ValueError:
        return []
    if adapter.parameters is None or not adapter.parameters.exclusive_parameter_groups:
        return []
    return adapter.parameters.exclusive_parameter_groups


def _validate_exclusive_groups(
    provider: str,
    *,
    temperature: float | None,
    top_p: float | None,
    errors: list[str],
) -> None:
    values = {"temperature": temperature, "top_p": top_p}
    for group in _get_exclusive_groups(provider):
        present = [field for field in group if values.get(field) is not None]
        if len(present) > 1:
            errors.append(
                f"{' and '.join(present)} cannot both be set for provider '{provider}'"
            )


def _validate_value(
    provider: str, field: str, value: float | int, errors: list[str]
) -> None:
    spec = _get_spec(provider, field)
    if spec is None:
        return
    if spec.min is not None and value < spec.min:
        errors.append(f"{field} must be >= {spec.min} for provider '{provider}'")
    if spec.max is not None and value > spec.max:
        errors.append(f"{field} must be <= {spec.max} for provider '{provider}'")


def validate_model_config_parameters(
    provider: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    top_p: float | None = None,
) -> None:
    errors: list[str] = []
    if temperature is not None:
        _validate_value(provider, "temperature", temperature, errors)
    if max_tokens is not None:
        _validate_value(provider, "max_tokens", max_tokens, errors)
    if top_p is not None:
        _validate_value(provider, "top_p", top_p, errors)
    _validate_exclusive_groups(
        provider, temperature=temperature, top_p=top_p, errors=errors
    )
    if errors:
        raise InvalidParameterError("; ".join(errors))


def resolve_provider_settings(provider: str, settings: dict) -> dict:
    """Drop lower-priority params when a provider forbids sending multiple values."""
    resolved = dict(settings)
    for group in _get_exclusive_groups(provider):
        present = [field for field in group if resolved.get(field) is not None]
        if len(present) > 1:
            for field in present[1:]:
                resolved.pop(field, None)
    return resolved


def clamp_model_config_parameter(
    provider: str, field: str, value: float | int
) -> float | int:
    spec = _get_spec(provider, field)
    if spec is None:
        return value
    if spec.min is not None and value < spec.min:
        return spec.min if isinstance(value, int) else spec.min
    if spec.max is not None and value > spec.max:
        return spec.max if isinstance(value, int) else spec.max
    return value
