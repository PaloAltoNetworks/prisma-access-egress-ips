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

You should see `Trusting additional CA certificates from /certs/corp-ca.pem`. A line starting with
`Skipping` means the file isn't valid PEM; re-export it in Base-64/PEM format.

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
- If you route the container through an explicit proxy (`HTTPS_PROXY`), queries use it but the
  certificate details in the error dialog are read over a direct connection. They may be missing,
  or describe the direct path rather than the proxied one.
- If only some environments fail while the tool searches for the one that accepts your API key,
  the query carries on and those hosts are listed above the form. **View details** opens the same
  dialog for each one.
- If you can't get the CA, the dialog offers to skip certificate verification for the rest of
  the browser session (until the page is reloaded or closed). Only do that on a network you
  trust: your API key or client secret is sent over connections whose identity isn't verified.
