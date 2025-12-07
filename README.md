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
