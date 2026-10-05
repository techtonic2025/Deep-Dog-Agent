from pdf_export import _inline, report_to_pdf


def test_inline_does_not_linkify_url_inside_code_span():
    markup = _inline(
        "Usa `https://api.openai.com/v1` oppure "
        "[OpenRouter](https://openrouter.ai/api/v1)."
    )

    assert '<font name="Courier">https://api.openai.com/v1</font>' in markup
    assert '<link href="https://openrouter.ai/api/v1"' in markup
    assert "</fon</u>" not in markup


def test_report_with_code_url_generates_pdf():
    report = (
        "# Test\n\n"
        "L'endpoint è `https://api.openai.com/v1` e il modello è "
        "`openai/gpt-4o-mini`. Visita https://openrouter.ai/api/v1."
    )

    pdf = report_to_pdf(report)

    assert pdf.startswith(b"%PDF")
