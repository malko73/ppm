import os, sys
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
sys.path.insert(0, os.getcwd())

import django
django.setup()

from projects.models import Page
from projects.services.pdf_renderer import PDFRenderService

p = Page.objects.get(id=670)
proj = p.project
print(f"Page: id={p.id} finalized={p.is_finalized}")
print(f"Project: id={proj.id} title={proj.title}")
print(f"Template: {proj.template_file.name if proj.template_file else None}")

pdf_bytes = PDFRenderService.render_single_page_bytes(proj, p, output_profile="preview")
print(f"PDF generated: {len(pdf_bytes)} bytes")
with open("/tmp/page_670.pdf", "wb") as f:
    f.write(pdf_bytes)
print("SAVED")
