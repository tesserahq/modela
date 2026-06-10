import ipaddress
import socket
from urllib.parse import urlparse

from app.exceptions.invalid_parameter_error import InvalidParameterError

_ALLOWED_SCHEMES = {"https"}

# RFC1918 + loopback + link-local + unspecified
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_private_ip(ip_str: str) -> bool:
    """Return True if ip_str is in a blocked range. Raises ValueError if not a valid IP."""
    addr = ipaddress.ip_address(ip_str)
    return any(addr in net for net in _BLOCKED_NETWORKS)


def validate_file_url(url: str) -> None:
    """Raise InvalidParameterError if url is not a safe, externally-reachable HTTPS URL.

    Guards against SSRF by:
    - requiring https scheme
    - rejecting bare IP literals that are private/loopback
    - resolving the hostname and rejecting any result in private/loopback ranges
    """
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise InvalidParameterError(
            f"file_url scheme '{parsed.scheme}' is not allowed. Only HTTPS URLs are accepted."
        )

    host = parsed.hostname
    if not host:
        raise InvalidParameterError("file_url is missing a hostname.")

    host = host.rstrip(".").lower()

    # If the host is a bare IP literal, validate it directly before DNS resolution.
    # ValueError means it's a hostname, not an IP — fall through to DNS resolution.
    try:
        if _is_private_ip(host):
            raise InvalidParameterError(
                "file_url must not point to a private or loopback address."
            )
    except ValueError:
        pass

    # Resolve hostname and check every returned address
    try:
        results = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise InvalidParameterError(
            f"file_url hostname '{host}' could not be resolved: {exc}"
        ) from exc

    for _family, _type, _proto, _canonname, sockaddr in results:
        ip = sockaddr[0]
        try:
            if _is_private_ip(ip):
                raise InvalidParameterError(
                    "file_url must not point to a private or loopback address."
                )
        except ValueError:
            pass
