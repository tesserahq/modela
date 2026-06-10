import pytest
from unittest.mock import patch
from app.exceptions.invalid_parameter_error import InvalidParameterError
from app.utils.url_validation import validate_file_url


def _mock_resolve(public_ip: str):
    """Return a getaddrinfo-style result for a single IPv4 address."""
    return [(2, 1, 6, "", (public_ip, 0))]


# --- scheme checks ---


def test_rejects_http():
    with pytest.raises(InvalidParameterError, match="scheme"):
        validate_file_url("http://example.com/doc.pdf")


def test_rejects_ftp():
    with pytest.raises(InvalidParameterError, match="scheme"):
        validate_file_url("ftp://example.com/doc.pdf")


def test_rejects_file_scheme():
    with pytest.raises(InvalidParameterError, match="scheme"):
        validate_file_url("file:///etc/passwd")


# --- bare IP literals ---


def test_rejects_loopback_ip():
    with pytest.raises(InvalidParameterError, match="private or loopback"):
        validate_file_url("https://127.0.0.1/doc.pdf")


def test_rejects_rfc1918_10():
    with pytest.raises(InvalidParameterError, match="private or loopback"):
        validate_file_url("https://10.0.0.1/doc.pdf")


def test_rejects_rfc1918_172():
    with pytest.raises(InvalidParameterError, match="private or loopback"):
        validate_file_url("https://172.16.0.1/doc.pdf")


def test_rejects_rfc1918_192168():
    with pytest.raises(InvalidParameterError, match="private or loopback"):
        validate_file_url("https://192.168.1.1/doc.pdf")


def test_rejects_link_local():
    with pytest.raises(InvalidParameterError, match="private or loopback"):
        validate_file_url("https://169.254.169.254/latest/meta-data/")


# --- DNS resolution ---


def test_rejects_hostname_resolving_to_private():
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.5", 0))]):
        with pytest.raises(InvalidParameterError, match="private or loopback"):
            validate_file_url("https://internal.corp/doc.pdf")


def test_rejects_unresolvable_hostname():
    import socket

    with patch("socket.getaddrinfo", side_effect=socket.gaierror("NXDOMAIN")):
        with pytest.raises(InvalidParameterError, match="could not be resolved"):
            validate_file_url("https://this-does-not-exist.invalid/doc.pdf")


def test_accepts_public_hostname():
    with patch("socket.getaddrinfo", return_value=_mock_resolve("93.184.216.34")):
        validate_file_url("https://example.com/doc.pdf")  # should not raise


def test_accepts_public_ip():
    with patch("socket.getaddrinfo", return_value=_mock_resolve("93.184.216.34")):
        validate_file_url("https://93.184.216.34/doc.pdf")  # should not raise


def test_rejects_missing_hostname():
    with pytest.raises(InvalidParameterError, match="hostname"):
        validate_file_url("https:///path/only")
