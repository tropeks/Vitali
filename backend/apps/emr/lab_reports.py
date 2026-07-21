from django.template.loader import render_to_string


def render_lab_report_pdf(order) -> bytes:
    """Render the exact bytes that are hashed and signed."""
    from weasyprint import HTML

    html = render_to_string("emr/lab_report.html", {"order": order})
    return HTML(string=html).write_pdf()
