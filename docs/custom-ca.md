# Trusting a custom CA (SSL decryption)

Many corporate networks decrypt outbound TLS. A proxy or firewall re-signs each connection with
the organization's own root CA. Your laptop trusts that CA, but the container doesn't, so every
query fails with **Certificate verification failed**.

The fix is to give the container your organization's CA. Verification stays on: the container
still checks every certificate, and simply accepts your organization's CA as well as the public
ones.

## 1. Get the CA certificate

You need the root CA (or the decryption/forward-trust CA) as a PEM file, the text format starting
with `-----BEGIN CERTIFICATE-----`. Your IT or security team can provide it. To export it yourself:

**macOS.** Find the CA in Keychain Access (System keychain, Certificates). The last "issued by"
name in the tool's certificate chain is a good search term. Then export it from Terminal:

```bash
mkdir -p certs
security find-certificate -a -p -c "<CA common name>" /Library/Keychains/System.keychain > certs/corp-ca.pem
```

**Windows.** Open `certlm.msc` and go to Trusted Root Certification Authorities, then Certificates.
Right-click the CA, choose All Tasks, then Export, and pick **Base-64 encoded X.509 (.CER)**. Save it
into a `certs` folder as `corp-ca.pem`.

**Linux.** Corporate CAs are usually in `/usr/local/share/ca-certificates/` (Debian/Ubuntu) or
`/etc/pki/ca-trust/source/anchors/` (RHEL/Fedora). Copy the file into `certs/` with a `.pem` or
`.crt` extension.

Check that the file is PEM:

```bash
head -1 certs/corp-ca.pem   # -----BEGIN CERTIFICATE-----
```

## 2. Mount it into the container

The container trusts every `*.pem` and `*.crt` file in `/certs`, in addition to the public roots.
In `compose.yml`, uncomment the `volumes` lines so the `certs` folder next to the compose file is
mounted read-only:

```yaml
services:
  app:
    # ...
    volumes:
      - ./certs:/certs:ro
```

Then restart:

```bash
docker compose up -d --force-recreate
```

With `docker run`, add `-v "$PWD/certs:/certs:ro"`.

## 3. Confirm it loaded

```bash
docker compose logs app | grep -i "CA certificates"
```

You should see `Trusting additional CA certificates from /certs/corp-ca.pem`. A line containing
`Skipping` means the file couldn't be read as PEM: re-export it in Base-64/PEM format, and check
that it's readable by all users (the container runs as UID 65532).

The certificates are loaded on the first query after the container starts, so run one query
before checking the log.

## Notes

- When a custom CA is loaded, the container relaxes Python's strict RFC 5280 certificate format
  checks, which many corporate CAs fail (for example, "Missing Authority Key Identifier"). Chain
  and hostname verification are unaffected.
- The certificate file is public information: it contains no private key. Never put a private
  key in `certs/`.
- The error dialog shows the certificate chain the container was given. If it ends at your
  organization's CA, that's the certificate to export. If it ends at a public CA, the reason it
  shows usually explains the failure: an expired certificate, a hostname mismatch, or a wrong
  clock on the machine running the container. If you don't recognize the CA, the connection
  may be intercepted.
- If only some environments fail while the tool searches for the one that accepts your API key,
  the query carries on and those hosts are listed above the form. **View details** opens the same
  dialog for each one.
- If you can't get the CA, the dialog offers to trust the certificate it shows for the rest of
  the browser session (until the page is reloaded or closed). What it trusts depends on the
  failure:
  - **Untrusted issuer** (for example `self-signed certificate in certificate chain`): the last
    certificate in the chain, usually your organization's decryption CA. It's accepted for every
    host, and hostnames and expiry dates are still checked.
  - **Anything else** (for example an expired certificate or a hostname mismatch): only that exact
    certificate, and only for that host.

  A different certificate or host shows the dialog again. Approvals are listed under the
  **Query** button, where you can remove them. Only approve a certificate you recognize: your API
  key or client secret is sent to whoever holds it.
