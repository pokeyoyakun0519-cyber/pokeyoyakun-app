# Subscription authentication API contract

This contract adds passwordless subscription authentication on top of the
existing manual-license API. Existing `/api/v1/licenses/*` behavior remains
unchanged.

## Public endpoints

`POST /api/v1/subscriptions/auth/request-code`

```json
{"email":"buyer@example.com","app_version":"1.x"}
```

The server returns the same public message whether or not the address exists.
For an eligible Stripe customer it sends a six-digit code through Resend. The
server stores only a salted/peppered digest. Codes expire after 10 minutes,
cannot be resent for 60 seconds, and become invalid after five failed attempts.
Email/IP rate limits are server-side. Resend configuration comes only from
`POKEYOYA_RESEND_API_KEY` and `POKEYOYA_RESEND_FROM_EMAIL`; missing configuration
fails closed.

`POST /api/v1/subscriptions/auth/verify-code`

```json
{
  "email":"buyer@example.com",
  "code":"123456",
  "device_id":"opaque-device-id",
  "app_version":"1.x"
}
```

On success, the response contains an internal `license_key` and the same signed
`license_token` shape as the existing activation API. The desktop client must
verify that signature against the bundled public key before storing the internal
key or granting access. The UI never displays the key. A subscription license is
limited to two devices; a third new device is rejected clearly.

## Stripe webhook

`POST /api/v1/stripe/webhook` accepts the raw request body only when the
`Stripe-Signature` HMAC verifies with `POKEYOYA_STRIPE_WEBHOOK_SECRET` and the
timestamp is within 300 seconds. Event IDs are unique and processing is
idempotent. Supported events are:

- `checkout.session.completed`
- `customer.subscription.created`
- `invoice.paid`
- `invoice.payment_failed`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Price IDs are environment-configured allowlists mapping to `founder_300` and
`standard_500`; no secret key or price decision is embedded in the client.
Stripe's `current_period_end` is authoritative.

## Entitlement policy

- `active`, `trialing`: allowed.
- cancellation scheduled/canceled: allowed only through `current_period_end`.
- `past_due`: allowed through configurable grace, default five days.
- `unpaid`, `expired`, or period ended: denied.

The server synchronizes this entitlement into one internally issued license with
`max_devices=2`. Manual licenses keep their existing issuance, device limit, and
verification behavior.

## Server-side records

The server owns Stripe customer/subscription IDs, normalized purchase email,
plan, subscription/payment status, current period end, cancellation/end times,
grace end, internal license reference, registered devices, and last
authentication time. OTP values, Resend keys, Stripe secrets, webhook bodies,
and full internal license keys must not be written to logs.
