"""
Certificate approvals against real TLS servers: what an approval trusts, what it still
checks, and that nothing is sent to a server before its certificate is verified.
"""

import asyncio
import datetime
import select
import socket
import ssl
import threading

import certifi

import httpx
import pytest
import trustme

from app.models import AnchorApproval, LeafApproval
from app.services import prisma_client, tls

NOW = datetime.datetime.now(datetime.timezone.utc)
EXPIRED = {"not_before": NOW - datetime.timedelta(days=10), "not_after": NOW - datetime.timedelta(days=1)}
RESPONSE = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{}"


class TLSServer:
    """Serves one certificate on 127.0.0.1 and records what each connection sent after the handshake."""

    def __init__(self, cert: trustme.LeafCert, leaf_only: bool = False):
        self.ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        if leaf_only:
            with cert.cert_chain_pems[0].tempfile() as crt, cert.private_key_pem.tempfile() as key:
                self.ctx.load_cert_chain(crt, key)
        else:
            cert.configure_cert(self.ctx)
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.received: list[bytes] = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                try:
                    with self.ctx.wrap_socket(conn, server_side=True) as tls_conn:
                        self.received.append(tls_conn.recv(65536))
                        tls_conn.sendall(RESPONSE)
                except (ssl.SSLError, OSError):
                    self.received.append(b"")

    def close(self):
        self.sock.close()


class ConnectProxy:
    """A CONNECT proxy on 127.0.0.1, plain HTTP or (given a certificate) HTTPS; records each CONNECT line."""

    def __init__(self, cert: trustme.LeafCert | None = None):
        self.ctx = None
        if cert:
            self.ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            cert.configure_cert(self.ctx)
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.connects: list[str] = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._tunnel, args=(conn,), daemon=True).start()

    def _tunnel(self, conn):
        try:
            if self.ctx:
                conn = self.ctx.wrap_socket(conn, server_side=True)
            head = b""
            while b"\r\n\r\n" not in head:
                head += conn.recv(4096)
            line = head.split(b"\r\n")[0].decode()
            self.connects.append(line)
            port = int(line.split()[1].rsplit(":", 1)[1])
            with socket.create_connection(("127.0.0.1", port)) as upstream:
                conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                self._pipe(conn, upstream)
        except (ssl.SSLError, OSError):
            pass
        finally:
            conn.close()

    @staticmethod
    def _pipe(a, b):
        while True:
            ready = [s for s in (a, b) if isinstance(s, ssl.SSLSocket) and s.pending()]
            ready = ready or select.select([a, b], [], [], 5)[0]
            if not ready:
                return
            for s in ready:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)

    def close(self):
        self.sock.close()


@pytest.fixture
def serve():
    servers = []

    def start(cert, leaf_only=False):
        servers.append(TLSServer(cert, leaf_only))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


@pytest.fixture(scope="module")
def corp():
    """An untrusted root and an intermediate that signs leaves; servers present leaf + intermediate."""
    root = trustme.CA(organization_name="Example Corp")
    return root, root.create_child_ca()


def handshake(ctx: ssl.SSLContext, port: int, hostname: str) -> bool:
    with socket.create_connection(("127.0.0.1", port)) as sock:
        try:
            with ctx.wrap_socket(sock, server_hostname=hostname):
                return True
        except ssl.SSLCertVerificationError:
            return False


def anchor(ca) -> AnchorApproval:
    return AnchorApproval(kind="anchor", pem=ca.cert_pem.bytes().decode())


def leaf(host: str, cert: trustme.LeafCert) -> LeafApproval:
    return LeafApproval(kind="leaf", host=host, pem=cert.cert_chain_pems[0].bytes().decode())


def test_untrusted_ca_is_rejected_without_approval(serve, corp):
    _, issuer = corp
    server = serve(issuer.issue_cert("api.example.com"))
    assert not handshake(tls.context_for("api.example.com"), server.port, "api.example.com")


def test_approved_ca_trusts_its_certificates_for_any_matching_host(serve, corp):
    _, issuer = corp
    approvals = [anchor(issuer)]
    api = serve(issuer.issue_cert("api.example.com"))
    other = serve(issuer.issue_cert("other.example.com"))

    assert handshake(tls.context_for("api.example.com", approvals), api.port, "api.example.com")
    assert handshake(tls.context_for("other.example.com", approvals), other.port, "other.example.com")


def test_approved_ca_still_checks_hostname_and_expiry(serve, corp):
    _, issuer = corp
    approvals = [anchor(issuer)]
    api = serve(issuer.issue_cert("api.example.com"))
    expired = serve(issuer.issue_cert("api.example.com", **EXPIRED))

    assert not handshake(tls.context_for("evil.example.com", approvals), api.port, "evil.example.com")
    assert not handshake(tls.context_for("api.example.com", approvals), expired.port, "api.example.com")


def test_approved_leaf_works_only_for_that_certificate_and_host(serve, corp):
    _, issuer = corp
    approved = issuer.issue_cert("api.example.com", **EXPIRED)
    approvals = [leaf("api.example.com", approved)]
    server = serve(approved)

    assert handshake(tls.context_for("api.example.com", approvals), server.port, "api.example.com")
    # The approval doesn't apply to any other host
    assert not handshake(tls.context_for("other.example.com", approvals), server.port, "other.example.com")


def test_approved_leaf_refuses_any_other_certificate_for_the_host(serve, corp):
    root, issuer = corp
    approvals = [leaf("api.example.com", issuer.issue_cert("api.example.com", **EXPIRED))]
    another_expired = serve(issuer.issue_cert("api.example.com", **EXPIRED))
    valid_same_issuer = serve(issuer.issue_cert("api.example.com"))
    ctx = tls.context_for("api.example.com", approvals + [anchor(root)])

    assert not handshake(ctx, another_expired.port, "api.example.com")
    assert not handshake(ctx, valid_same_issuer.port, "api.example.com")


def test_nothing_is_sent_before_verification(serve, corp):
    _, issuer = corp
    server = serve(issuer.issue_cert("localhost"))
    url = f"https://localhost:{server.port}/"
    headers = {"header-api-key": "secret-api-key"}

    async def call(approvals):
        async with prisma_client._client(url, approvals) as client:
            return await client.post(url, headers=headers, json={})

    with pytest.raises(httpx.ConnectError):
        asyncio.run(call([]))
    assert b"secret-api-key" not in b"".join(server.received)

    assert asyncio.run(call([anchor(issuer)])).status_code == 200
    assert b"secret-api-key" in server.received[-1]


def test_presented_chain_is_read_without_credentials(serve, corp):
    _, issuer = corp
    server = serve(issuer.issue_cert("localhost"))

    ders, parsed = asyncio.run(tls._presented_chain(f"https://localhost:{server.port}/api/v1/query"))

    assert len(ders) == len(parsed) == 2
    assert ssl.DER_cert_to_PEM_cert(ders[-1]) == issuer.cert_pem.bytes().decode()
    request = server.received[-1]
    assert request.startswith(b"GET / ")
    assert b"api-key" not in request.lower() and b"authorization" not in request.lower()


@pytest.fixture
def proxy(monkeypatch):
    proxies = []
    for name in ("NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(name, raising=False)

    def start(scheme="http", cert=None):
        proxies.append(ConnectProxy(cert))
        monkeypatch.setenv("HTTPS_PROXY", f"{scheme}://127.0.0.1:{proxies[-1].port}")
        return proxies[-1]

    yield start
    for p in proxies:
        p.close()


def test_presented_chain_is_read_through_the_proxy(serve, corp, proxy):
    _, issuer = corp
    server = serve(issuer.issue_cert("localhost"))
    via = proxy()

    ders, _ = asyncio.run(tls._presented_chain(f"https://localhost:{server.port}/"))

    assert via.connects == [f"CONNECT localhost:{server.port} HTTP/1.1"]
    assert ssl.DER_cert_to_PEM_cert(ders[-1]) == issuer.cert_pem.bytes().decode()


def test_presented_chain_through_an_https_proxy_is_the_servers_not_the_proxys(serve, corp, proxy, tmp_path, monkeypatch):
    _, issuer = corp
    server = serve(issuer.issue_cert("localhost"))
    proxy_ca = trustme.CA(organization_name="Proxy Corp")
    # httpcore verifies the proxy's own certificate against certifi's bundle
    proxy_ca.cert_pem.write_to_path(str(tmp_path / "proxy-ca.pem"))
    monkeypatch.setattr(certifi, "where", lambda: str(tmp_path / "proxy-ca.pem"))
    via = proxy("https", proxy_ca.issue_cert("127.0.0.1"))

    ders, parsed = asyncio.run(tls._presented_chain(f"https://localhost:{server.port}/"))

    assert via.connects == [f"CONNECT localhost:{server.port} HTTP/1.1"]
    assert ssl.DER_cert_to_PEM_cert(ders[-1]) == issuer.cert_pem.bytes().decode()
    assert all("Proxy Corp" not in str(c) for c in parsed)


async def _failure_detail(url: str, approvals) -> dict:
    try:
        async with prisma_client._client(url, approvals) as client:
            await client.get(url)
    except httpx.ConnectError as exc:
        return (await tls.verification_failed(url, tls.cert_verification_error(exc))).detail
    raise AssertionError("verification unexpectedly succeeded")


def test_untrusted_issuer_offers_the_top_certificate_as_an_anchor(serve, corp):
    _, issuer = corp
    server = serve(issuer.issue_cert("localhost"))

    detail = asyncio.run(_failure_detail(f"https://localhost:{server.port}/", []))

    assert detail["approval"] == {"kind": "anchor", "pem": issuer.cert_pem.bytes().decode()}
    assert detail["approval_label"].startswith("Trust ")
    AnchorApproval.model_validate(detail["approval"])


def test_leaf_only_chain_offers_that_leaf_not_an_anchor(serve, corp):
    _, issuer = corp
    cert = issuer.issue_cert("localhost")
    server = serve(cert, leaf_only=True)

    detail = asyncio.run(_failure_detail(f"https://localhost:{server.port}/", []))

    assert detail["approval"] == {
        "kind": "leaf", "host": "localhost", "pem": cert.cert_chain_pems[0].bytes().decode(),
    }
    assert detail["approval_label"] == "Accept this certificate for localhost for this session"
    approvals = [LeafApproval.model_validate(detail["approval"])]
    assert handshake(tls.context_for("localhost", approvals), server.port, "localhost")


def test_expired_certificate_offers_only_that_leaf_for_that_host(serve, corp):
    root, issuer = corp
    cert = issuer.issue_cert("localhost", **EXPIRED)
    server = serve(cert)

    detail = asyncio.run(_failure_detail(f"https://localhost:{server.port}/", [anchor(root)]))

    assert detail["approval"] == {
        "kind": "leaf", "host": "localhost", "pem": cert.cert_chain_pems[0].bytes().decode(),
    }
    assert detail["approval_label"] == "Accept this expired certificate for localhost for this session"
    # Approving it makes the next request succeed
    approvals = [LeafApproval.model_validate(detail["approval"])]
    assert handshake(tls.context_for("localhost", approvals), server.port, "localhost")


def test_no_approval_offered_when_the_chain_cannot_be_read(monkeypatch):
    async def unreadable(url):
        return None

    monkeypatch.setattr(tls, "_presented_chain", unreadable)
    err = ssl.SSLCertVerificationError(1, "certificate verify failed")
    err.verify_code, err.verify_message = 20, "unable to get local issuer certificate"

    detail = asyncio.run(tls.verification_failed("https://api.example.com/", err)).detail

    assert detail["certificate"] is None
    assert detail["approval"] is None
