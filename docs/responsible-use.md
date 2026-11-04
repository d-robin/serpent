# Responsible use

Serpent can pool several accounts and rotate between them. **That does not mean
every provider allows you to do so.** Read this before you add more than one
account to the same provider.

## The risk

Many SERP and scraping providers prohibit, in their terms of service, any of:

- registering several free accounts to obtain more free credits than one account
  gets,
- sharing or reselling an account's quota,
- using automation to evade rate limits or usage caps.

If a provider decides you broke its terms it can **suspend or delete the
accounts, void unused credits, block your payment method or IP address, or ban
you**. Serpent cannot detect this in advance. A suspended account shows up as an
`invalid` key after its first `401` or `403`.

## Where this is generally fine

- Several accounts that legitimately belong to **different people or
  organisations** you are authorised to act for.
- Accounts the provider explicitly lets you create, for example separate projects,
  environments or teams under its own rules.
- **Different providers.** Chains that fall back from one provider to another carry
  no multi-account risk with any single provider.
- A single paid account, where Serpent is only adding caching, quota tracking and
  failover.

## What Serpent does about it

- Snake Charmer shows a warning on every provider with more than one account, and
  asks you to confirm before you add a second account to a provider.
- `serpent accounts add` prints a reminder on stderr when the provider already has
  accounts.
- Nothing is blocked. The decision and the responsibility are yours.

## Your checklist

1. Read the provider's current terms and acceptable-use policy.
2. If they are unclear, ask the provider's support in writing.
3. Prefer paid plans or separate legitimate accounts over free-tier stacking.
4. Keep `QUOTA_RESERVE` above zero and watch for `invalid` accounts.

The maintainers of Serpent do not give legal advice and are not responsible for
how you use the software or for any action a provider takes against your accounts.
