# Cross-port proxy URL adaptation

## Approved requirement

A proxied HTTP frontend may call an HTTP backend on another loopback or RFC1918 address/port. Adapt those URLs through the same Share origin without registering services or changing the frontend configuration. The user approved adding this to the existing dynamic proxy.

## Design

- Server HTML/CSS and Location rewriting maps local HTTP authorities to their own `/proxy/host:port/` prefix.
- The injected browser adapter does the same for fetch/Request, XMLHttpRequest (including Axios using its XHR adapter), WebSocket, EventSource, and supported DOM URL attributes.
- Already-proxied paths remain unchanged, including paths for another service. Preserve query strings, fragments, request methods and payloads.
- Retain the existing proxy request Origin conversion to the destination service and cookie isolation by target prefix. Do not change backend authentication policy as part of URL adaptation.
- Accept only localhost, loopback and RFC1918 IP destinations; the server remains authoritative for blocked ports. Do not rewrite public/metadata destinations or silently downgrade HTTPS/WSS upstreams. Protocol-relative local resource URLs refer to HTTP upstream services in this HTTP-only proxy.
- No arbitrary JavaScript/JSON string rewriting. Workers, restrictive CSP, JavaScript navigation, and unsupported dynamic resource patterns can still need application changes.

## Verification and scope

Add failing Python and Node regressions, then exercise two isolated local HTTP services through an authenticated Share fixture in Chromium. Verify API methods/body, stream/WebSocket, images and redirects. Run the existing suite. Do not restart PHP or production Share, change actual service configuration, commit, push, or publish a release.
