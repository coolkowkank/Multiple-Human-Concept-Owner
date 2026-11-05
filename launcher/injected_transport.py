"""Offline adapter over an INJECTED transport callable. Makes no network call.

The callable owns every execution protocol concern (allowance, ledger, caps,
retries). This adapter never calls a provider itself and cannot bypass a ledger:
with no callable it refuses. It only maps a transport result into the audit
wrapper's reported-usage evidence.

Expected result dict: {'kind': 'ok', 'content': str, 'usage': {...} | None}.
Anything else is a failed call: raises AdapterError and leaves last_call None.
Missing or malformed usage stays unknown (reported_call_evidence marks it);
it is never turned into zero. The response id is always None here (the Ryan-lane
transport captures none). Reported, not verified.
"""
from __future__ import annotations

from .adapters import Adapter, AdapterError, parse_response


class InjectedTransportAdapter(Adapter):
    # Default class never claims provider origin: an injected callable is
    # untrusted (it may be a fake). Use ProviderInjectedTransportAdapter with an
    # explicit trust binding for a real provider transport.
    REPORTS_PROVIDER_USAGE = False

    def __init__(self, transport):
        if not callable(transport):
            raise AdapterError('injected transport must be callable (fail-closed)')
        self._transport = transport
        self.last_call = None

    def complete(self, system, prompt):
        self.last_call = None  # failed calls never leave stale evidence
        result = self._transport(system, prompt)
        if not isinstance(result, dict) or result.get('kind') != 'ok':
            kind = result.get('kind') if isinstance(result, dict) else None
            raise AdapterError('transport did not return ok'
                               + (f' (kind={kind!r})' if isinstance(kind, str) and len(kind) <= 16 and kind.isalnum() else ''))
        content = result.get('content')
        if not isinstance(content, str):
            raise AdapterError('transport ok result has no text content')
        # The transport returned ok, so the call happened (and may be billed):
        # keep its reported usage even if the text then fails to parse.
        self.last_call = {'origin': 'provider', 'response_id': None,
                          'usage': result.get('usage')}
        return parse_response(content)


class ProviderInjectedTransportAdapter(InjectedTransportAdapter):
    """Same mapping, class-level provider capability, explicit trust binding.

    The caller asserts, in wiring code that a reviewer can see, that `transport`
    is a real provider transport (not a fake). This class cannot verify that.
    """
    REPORTS_PROVIDER_USAGE = True

    def __init__(self, transport, *, trust_provider_transport=False):
        if trust_provider_transport is not True:
            raise AdapterError('trust_provider_transport=True required (explicit '
                               'binding that the callable is a real provider transport)')
        super().__init__(transport)
