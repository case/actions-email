# actions-email

This is a simple GitHub Action for sending emails via these services:

- [Postmark](https://postmarkapp.com/)
- [Resend](https://resend.com/)

It uses the Python stdlib exclusively, there are no other dependencies - `send_email.py` is the script.

## Inputs

**Required environment variables:**

- `POSTMARK_API_TOKEN` or `RESEND_API_KEY` - Depending on the provider you're using
- `EMAIL_FROM` - Email "From" address
- `EMAIL_TO` - Email "To" address

Values used in the workflow:

- `provider` - Either `postmark` or `resend`
- `subject` - The email subject
- `body_text` and/or `body_html` - The email body (at least one required)

## Usage

Add a step to your Actions code like this:

```yaml
- uses: case/actions-email@v1
  env:
    POSTMARK_API_TOKEN: ${{ secrets.POSTMARK_API_TOKEN }} # If using Postmark
    RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }} # If using Resend
    EMAIL_FROM: ${{ secrets.EMAIL_FROM }}
    EMAIL_TO: ${{ secrets.EMAIL_TO }}
  with:
    provider: resend # Or "postmark"
    subject: "Build completed"
    body_html: "<h1>Success!</h1>"
```

## Failure behaviour

The step fails with an `::error::` annotation, and never a traceback, when:

- a required environment variable or input is missing or empty, or `provider` is not `postmark` or `resend`. Nothing is sent
- the API key or token holds whitespace, control or non-ASCII characters. The error does not print it
- the provider rejects the request (any 4xx or 5xx). The provider's error body is printed, with the from and to addresses masked and the HTML and text bodies shown only as lengths. Inside that dump the runner ignores workflow commands
- the connection fails, DNS fails, or the send takes longer than 30 seconds

The 30 second limit covers the whole send, from DNS lookup to the last byte of the response. There is no retry: a timeout can happen after the provider accepted the email, and a retry could send it twice.

A 2xx response always passes the step, even when its body is not JSON.

## Python

`send_email.py` runs on the runner's `python3`. CI tests it on Python 3.14, and ruff checks its syntax against Python 3.10. Older versions are not tested.

## Development

Tools come from `mise.toml`. `bin/setup` installs them, `bin/lint` runs every check, `bin/test` runs the tests, and `bin/ci` runs all three in order.

`bin/test` runs the stdlib `unittest` suite in `test/`. It needs no network and no credentials. Each test runs `send_email.py` with `test/stub/sitecustomize.py` on `PYTHONPATH`, which records the request and answers it, or forwards it to a fake provider on `127.0.0.1`. The tests cover payload shape for both providers, hostile subject and body values, missing inputs, HTTP errors, a provider that never answers or answers slowly, and a refused connection.

CI runs `bin/ci`, then runs the action itself (`uses: ./`) with hostile inputs against the same stub. That covers the `action.yml` wiring, which `bin/test` cannot reach.

## Sending a real test email

This sends real email through Resend and reads the key from 1Password, so it is never part of `bin/test` or CI:

```
op run --env-file=.env.op -- python3 send_email.py --test --from "sender@email.domain" --to "recipient@email.domain"
```
